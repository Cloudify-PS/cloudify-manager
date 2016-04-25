#########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  * See the License for the specific language governing permissions and
#  * limitations under the License.
#

import os
import StringIO
import traceback
from datetime import datetime

from flask import jsonify

from manager_rest import config
from manager_rest import utils
from manager_rest import models
from manager_rest.blueprints_manager import get_blueprints_manager
from manager_rest.constants import (MAINTENANCE_MODE_ACTIVATED,
                                    MAINTENANCE_MODE_STATUS_FILE,
                                    MAINTENANCE_MODE_ACTIVATING,
                                    MAINTENANCE_MODE_ACTIVE_ERROR_CODE,
                                    MAINTENANCE_MODE_ACTIVATING_ERROR_CODE)


FORBIDDEN_METHODS = ['POST', 'PATCH', 'PUT']
ALLOWED_ENDPOINTS = ['maintenance',
                     'status',
                     'version']


def get_maintenance_file_path():
    return os.path.join(
            config.instance().maintenance_folder,
            MAINTENANCE_MODE_STATUS_FILE)


def prepare_maintenance_dict(status,
                             activated_at='',
                             remaining_executions=None,
                             requested_by='',
                             activation_requested_at=''):
    state = {'status': status,
             'activated_at': activated_at,
             'remaining_executions': remaining_executions,
             'requested_by': requested_by,
             'activation_requested_at': activation_requested_at}
    return state


def maintenance_mode_handler(request):

    # enabling internal requests
    if is_internal_request(request) and is_bypass_maintenance_mode(request):
        return

    # Removing v*/ from the endpoint
    index = request.endpoint.find('/')
    request_endpoint = request.endpoint[index+1:]
    maintenance_file = os.path.join(
            config.instance().maintenance_folder,
            MAINTENANCE_MODE_STATUS_FILE)

    if os.path.isfile(maintenance_file):
        state = utils.read_json_file(maintenance_file)
        if state['status'] == MAINTENANCE_MODE_ACTIVATING:
            running_executions = get_running_executions()
            if not running_executions:
                now = str(datetime.now())
                state = prepare_maintenance_dict(
                        MAINTENANCE_MODE_ACTIVATED,
                        activated_at=now,
                        remaining_executions=None,
                        requested_by=state['requested_by'],
                        activation_requested_at=state[
                            'activation_requested_at'])
                utils.write_dict_to_json_file(maintenance_file, state)
            else:
                result = handle_activating_mode(
                        state=state,
                        request=request,
                        request_endpoint=request_endpoint)
                if result:
                    return result

        if check_allowed_endpoint(request_endpoint):
            return

        if state['status'] == MAINTENANCE_MODE_ACTIVATED:
            return maintenance_mode_error()


def handle_activating_mode(state, request, request_endpoint):
    status = state['status']

    if request_endpoint == 'snapshots/<string:snapshot_id>':
        if request.method in FORBIDDEN_METHODS:
            return _return_maintenance_error(status)
    if request_endpoint == 'snapshots/' \
                           '<string:snapshot_id>/restore':
        return _return_maintenance_error(status)

    if request_endpoint == 'executions':
        if request.method in FORBIDDEN_METHODS:
            return _return_maintenance_error(status)

    if request_endpoint == 'deployments/<string:deployment_id>':
        if request.method in FORBIDDEN_METHODS:
            return _return_maintenance_error(status)

    if request_endpoint == 'deployment-modifications':
        if request.method in FORBIDDEN_METHODS:
            return _return_maintenance_error(status)

    return None


def _return_maintenance_error(status):
    if status == MAINTENANCE_MODE_ACTIVATED:
        return maintenance_mode_error()
    return activating_maintenance_mode_error()


def check_allowed_endpoint(request_endpoint):
    for endpoint in ALLOWED_ENDPOINTS:
        if request_endpoint.startswith(endpoint):
            return True
    return False


def get_running_executions():
    executions = get_blueprints_manager().executions_list(
            is_include_system_workflows=True).items
    running_executions = []
    for execution in executions:
        if execution.status not in models.Execution.END_STATES:
            running_executions.append({
                'id': execution.id,
                'status': execution.status,
                'deployment_id': execution.deployment_id,
                'workflow_id': execution.workflow_id
            })

    return running_executions


def is_internal_request(request):
    return 'REMOTE_ADDR' in request.headers.environ \
           and 'HTTP_HOST' in request.headers.environ \
           and request.headers.environ['REMOTE_ADDR'] == \
               request.headers.environ['HTTP_HOST']


def is_bypass_maintenance_mode(request):
    return request.headers.environ.get('HTTP_X_BYPASS_MAINTENANCE')


def maintenance_mode_error():
    # app.logger.exception(e)  # gets logged automatically
    s_traceback = StringIO.StringIO()
    traceback.print_exc(file=s_traceback)

    response = jsonify(
            {"message": "Request rejected since maintenance mode is active",
             "error_code": MAINTENANCE_MODE_ACTIVE_ERROR_CODE,
             "server_traceback": s_traceback.getvalue()})
    response.status_code = 503
    return response


def activating_maintenance_mode_error():
    # app.logger.exception(e)  # gets logged automatically
    s_traceback = StringIO.StringIO()
    traceback.print_exc(file=s_traceback)

    response = jsonify(
            {"message": "Request rejected while activating maintenance mode",
             "error_code": MAINTENANCE_MODE_ACTIVATING_ERROR_CODE,
             "server_traceback": s_traceback.getvalue()})
    response.status_code = 503
    return response
