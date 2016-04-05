#########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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
from datetime import datetime

import tempfile

import shutil

from flask.ext.restful_swagger import swagger

from flask_securest.rest_security import SecuredResource
from flask_securest import rest_security
from manager_rest import utils
from flask import request

from manager_rest.resources import (marshal_with,
                                    exceptions_handled,
                                    verify_json_content_type,
                                    CONVENTION_APPLICATION_BLUEPRINT_FILE)

from manager_rest import models
from manager_rest import responses_v2_1
from manager_rest import config
from manager_rest.blueprints_manager import get_blueprints_manager
from manager_rest.constants import (MAINTENANCE_MODE_ACTIVE,
                                    MAINTENANCE_MODE_STATUS_FILE,
                                    ACTIVATING_MAINTENANCE_MODE,
                                    NOT_IN_MAINTENANCE_MODE)

from dsl_parser.parser import parse_from_path
from manager_rest import utils
from deployment_update.manager import get_deployment_updates_manager
from manager_rest.resources_v2 import create_filters, paginate, sortable
from manager_rest.utils import create_filter_params_list_description


class MaintenanceMode(SecuredResource):
    @exceptions_handled
    @marshal_with(responses_v2_1.MaintenanceMode)
    def get(self, **kwargs):
        maintenance_file_path = _get_maintenance_file_path()
        if os.path.isfile(maintenance_file_path):
            state = utils.read_json_file(maintenance_file_path)

            if state['status'] == MAINTENANCE_MODE_ACTIVE:
                return state
            if state['status'] == ACTIVATING_MAINTENANCE_MODE:
                running_executions = utils.get_running_executions()
                if running_executions:
                    state['remaining_executions'] = running_executions
                    return state

                # No 'else' clause since this will never happen. If there are
                # no running executions, maintenance mode would have
                # been activated at the maintenance handler hook (server.py)

        else:
            return _prepare_maintenance_dict(NOT_IN_MAINTENANCE_MODE)


class MaintenanceModeAction(SecuredResource):
    @exceptions_handled
    @marshal_with(responses_v2_1.MaintenanceMode)
    def post(self, maintenance_action, **kwargs):
        maintenance_file_path = _get_maintenance_file_path()

        if maintenance_action == 'activate':
            if os.path.isfile(maintenance_file_path):
                state = utils.read_json_file(maintenance_file_path)
                return state, 304

            now = str(datetime.now())
            user = ''
            if rest_security._is_secured_request_context():
                user = rest_security.get_username()
            remaining_executions = utils.get_running_executions()
            utils.mkdirs(config.instance().maintenance_folder)
            new_state = _prepare_maintenance_dict(
                    status=ACTIVATING_MAINTENANCE_MODE,
                    activation_requested_at=now,
                    remaining_executions=remaining_executions,
                    requested_by=user)
            utils.write_dict_to_json_file(maintenance_file_path, new_state)

            return new_state

        if maintenance_action == 'deactivate':
            if not os.path.isfile(maintenance_file_path):
                return _prepare_maintenance_dict(NOT_IN_MAINTENANCE_MODE), 304
            os.remove(maintenance_file_path)
            return _prepare_maintenance_dict(NOT_IN_MAINTENANCE_MODE)


class DeploymentUpdateSteps(SecuredResource):
    @exceptions_handled
    @marshal_with(responses_v2_1.DeploymentUpdateStep)
    def post(self, update_id):
        verify_json_content_type()
        request_json = request.json

        manager = get_deployment_updates_manager()
        update_step = \
            manager.create_deployment_update_step(
                    update_id,
                    request_json.get('operation'),
                    request_json.get('entity_type'),
                    request_json.get('entity_id')
            )
        return update_step


class DeploymentUpdates(SecuredResource):
    @swagger.operation(
            responseClass='List[{0}]'.format(
                    responses_v2_1.DeploymentUpdate.__name__),
            nickname="listDeploymentUpdates",
            notes='Returns a list of deployment updates',
            parameters=create_filter_params_list_description(
                    models.DeploymentUpdate.fields,
                    'deployment updates'
            )
    )
    @exceptions_handled
    @marshal_with(responses_v2_1.DeploymentUpdate)
    @create_filters(models.DeploymentUpdate.fields)
    @paginate
    @sortable
    def get(self, _include=None, filters=None, pagination=None,
            sort=None, **kwargs):
        """
        List deployment modification stages
        """
        deployment_updates = \
            get_deployment_updates_manager().deployment_updates_list(
                    include=None, filters=None, pagination=None,
                    sort=None, **kwargs)
        return deployment_updates

    @swagger.operation(
            responseClass=responses_v2_1.DeploymentUpdate,
            nickname="uploadDeploymentUpdate",
            notes="Uploads an archive for staging",
            parameters=[{'name': 'deployment_id',
                         'description': 'The deployment id to update',
                         'required': True,
                         'allowMultiple': False,
                         'dataType': 'string',
                         'paramType': 'query'},
                        {'name': 'application_file_name',
                         'description': 'The name of the app blueprint',
                         'required': False,
                         'allowMultiple': False,
                         'dataType': 'string',
                         'paramType': 'string',
                         'defaultValue': 'blueprint.yaml'},
                        {'name': 'blueprint_archive_url',
                         'description': 'The path of the archive (only if the '
                                        'archive is an online resource',
                         'required': False,
                         'allowMultiple': False,
                         'dataType': 'string',
                         'paramType': 'query'}
                        ]
    )
    @exceptions_handled
    @marshal_with(responses_v2_1.DeploymentUpdate)
    def post(self, **kwargs):
        """
        Receives an archive to stage. This archive must contain a
        main blueprint file, and specify its name in the application_file_name,
        defaults to 'blueprint.yaml'

        :param kwargs:
        :return: update response
        """
        query_params = request.args
        main_blueprint_key = 'application_file_name'
        blueprint_archive_url_key = 'blueprint_archive_url'
        deployment_id = query_params['deployment_id']

        blueprint_filename = \
            query_params.get(main_blueprint_key,
                             CONVENTION_APPLICATION_BLUEPRINT_FILE)

        temp_dir = tempfile.mkdtemp()
        try:
            archive_destination = \
                os.path.join(temp_dir, "{0}-{1}"
                             .format(deployment_id, blueprint_filename))

            # Saving the archive locally
            utils.save_request_content_to_file(request, archive_destination,
                                               blueprint_archive_url_key,
                                               'blueprint')

            # Unpacking the archive
            relative_app_dir = \
                utils.extract_blueprint_archive_to_mgr(archive_destination,
                                                       temp_dir)

            # retrieving and parsing the blueprint
            temp_app_path = os.path.join(temp_dir, relative_app_dir,
                                         blueprint_filename)
            blueprint = parse_from_path(temp_app_path)

            # create a staging object
            update = get_deployment_updates_manager(). \
                stage_deployment_update(deployment_id, blueprint)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return update, 201


class DeploymentUpdateCommit(SecuredResource):
    @exceptions_handled
    @marshal_with(responses_v2_1.DeploymentUpdate)
    def post(self, update_id):
        manager = get_deployment_updates_manager()
        return manager.commit_deployment_update(update_id)


class DeploymentUpdateFinalizeCommit(SecuredResource):
    @exceptions_handled
    @marshal_with(responses_v2_1.DeploymentUpdate)
    def post(self, update_id):
        manager = get_deployment_updates_manager()
        return manager.finalize_commit(update_id)


def get_maintenance_file_path():
    return os.path.join(
        config.instance().maintenance_folder,
        MAINTENANCE_MODE_STATUS_FILE)


def write_maintenance_state(state):
    maintenance_file_path = get_maintenance_file_path()
    with open(maintenance_file_path, 'w') as f:
        f.write(state)
