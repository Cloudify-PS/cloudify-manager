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
import os
import mock
from nose.plugins.attrib import attr

from cloudify_rest_client import exceptions
from manager_rest.test import base_test
from base_test import BaseServerTestCase
from manager_rest import (storage_manager,
                          models,
                          utils)
from manager_rest.constants import (
    MAINTENANCE_MODE_ACTIVE,
    ACTIVATING_MAINTENANCE_MODE,
    NOT_IN_MAINTENANCE_MODE,
    MAINTENANCE_MODE_STATUS_FILE)


@attr(client_min_version=2.1, client_max_version=base_test.LATEST_API_VERSION)
class MaintenanceModeTest(BaseServerTestCase):

    def test_maintenance_mode_inactive(self):
        response = self.client.maintenance_mode.status()
        self.assertEqual(NOT_IN_MAINTENANCE_MODE, response.status)
        self.assertFalse(response.activation_requested_at)
        self.client.blueprints.list()

    def test_maintenance_activation(self):
        response = self.client.maintenance_mode.activate()
        self.assertEqual(ACTIVATING_MAINTENANCE_MODE, response.status)
        response = self.client.maintenance_mode.status()
        self.assertEqual(MAINTENANCE_MODE_ACTIVE, response.status)

        # Second invocation of status goes through a different route.
        response = self.client.maintenance_mode.status()
        self.assertEqual(MAINTENANCE_MODE_ACTIVE, response.status)

    def test_any_cmd_activates_maintenance_mode(self):
        response = self.client.maintenance_mode.activate()
        self.assertEqual(ACTIVATING_MAINTENANCE_MODE, response.status)
        self.assertRaises(exceptions.MaintenanceModeActiveError,
                          self.client.blueprints.upload,
                          blueprint_path=self.get_mock_blueprint_path(),
                          blueprint_id='b1')

        self.client.maintenance_mode.deactivate()

        response = self.client.maintenance_mode.activate()
        self.assertEqual(ACTIVATING_MAINTENANCE_MODE, response.status)
        self.client.manager.get_version()

        maintenance_file = os.path.join(self.maintenance_mode_dir,
                                        MAINTENANCE_MODE_STATUS_FILE)
        state = utils.read_json_file(maintenance_file)
        self.assertEqual(state['status'], MAINTENANCE_MODE_ACTIVE)

    def test_request_denial_in_maintenance_mode(self):
        self._activate_maintenance_mode()
        self.assertRaises(exceptions.MaintenanceModeActiveError,
                          self.client.blueprints.list)

    def test_request_approval_in_maintenance_mode(self):
        self._activate_maintenance_mode()

        self.client.maintenance_mode.status()
        self.client.manager.get_version()
        self.client.manager.get_status()

    def test_internal_request_approval_in_maintenance_mode(self):
        self._activate_maintenance_mode()

        with mock.patch('manager_rest.utils.is_internal_request'):
            with mock.patch('manager_rest.utils.is_bypass_maintenance_mode'):
                self.client.blueprints.list()

    def test_internal_request_denial_in_maintenance_mode(self):
        self._activate_maintenance_mode()

        with mock.patch('manager_rest.utils.is_internal_request'):
            self.assertRaises(exceptions.MaintenanceModeActiveError,
                              self.client.blueprints.list)

    def test_external_request_denial_in_maintenance_mode(self):
        self._activate_maintenance_mode()

        with mock.patch('manager_rest.utils.is_bypass_maintenance_mode'):
            self.assertRaises(exceptions.MaintenanceModeActiveError,
                              self.client.blueprints.list)

    def test_multiple_maintenance_mode_activations(self):
        self._activate_maintenance_mode()
        try:
            self._activate_maintenance_mode()
            self.fail('Expected the second start request to fail '
                      'since maintenance mode is already started.')
        except exceptions.NotModifiedError as e:
            self.assertEqual(304, e.status_code)
        self.assertTrue('already activated' in e.message)

    def test_transition_to_active(self):
        execution = self._start_maintenance_transition_mode()
        self._terminate_execution(execution.id)
        response = self.client.maintenance_mode.status()
        self.assertEqual(response.status, MAINTENANCE_MODE_ACTIVE)

    def test_deployment_denial_in_maintenance_transition_mode(self):
        self._start_maintenance_transition_mode()
        self.client.blueprints.upload(
                self.get_mock_blueprint_path(),
                blueprint_id='b1')
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.deployments.create,
                          blueprint_id='b1',
                          deployment_id='d1')

    def test_deployment_modification_denial_maintenance_transition_mode(self):
        self.put_deployment('d1', blueprint_id='b2')
        self._start_maintenance_transition_mode()
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.deployment_modifications.start,
                          deployment_id='d1',
                          nodes={})

    def test_snapshot_creation_denial_in_maintenance_transition_mode(self):
        self._start_maintenance_transition_mode()
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.snapshots.create,
                          snapshot_id='s1',
                          include_metrics=False,
                          include_credentials=False)

    def test_snapshot_restoration_denial_in_maintenance_transition_mode(self):
        self._start_maintenance_transition_mode()
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.snapshots.restore,
                          snapshot_id='s1')

    def test_executions_denial_in_maintenance_transition_mode(self):
        self._start_maintenance_transition_mode()
        self.client.blueprints.upload(
                self.get_mock_blueprint_path(),
                blueprint_id='b1')
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.executions.start,
                          deployment_id='d1',
                          workflow_id='install')

    def test_request_approval_in_maintenance_transition_mode(self):
        self._start_maintenance_transition_mode()
        try:
            self.client.blueprints.list()
            self.client.manager.get_version()
        except exceptions.CloudifyClientError:
            self.fail('An allowed rest request failed while '
                      'activating maintenance mode.')

    def test_execution_amount_maintenance_activated(self):
        self._activate_maintenance_mode()
        response = self.client.maintenance_mode.status()
        self.assertIsNone(response.remaining_executions)

    def test_execution_amount_maintenance_deactivated(self):
        self._activate_and_deactivate_maintenance_mode()
        response = self.client.maintenance_mode.status()
        self.assertIsNone(response.remaining_executions)

    def test_execution_amount_maintenance_activating(self):
        execution_info = self._start_maintenance_transition_mode()
        response = self.client.maintenance_mode.status()
        self.assertEqual(1, len(response.remaining_executions))
        self.assertEqual(execution_info.id,
                         response.remaining_executions[0]['id'])
        self.assertEqual(execution_info.deployment_id,
                         response.remaining_executions[0]['deployment_id'])
        self.assertEqual(execution_info.workflow_id,
                         response.remaining_executions[0]['workflow_id'])

    def test_trigger_time_maintenance_activated(self):
        self._activate_maintenance_mode()
        response = self.client.maintenance_mode.status()
        self.assertTrue(len(response.activated_at) > 0)

    def test_trigger_time_maintenance_deactivated(self):
        self._activate_and_deactivate_maintenance_mode()
        response = self.client.maintenance_mode.status()
        self.assertTrue(len(response.activated_at) == 0)

    def test_trigger_time_maintenance_activating(self):
        self._start_maintenance_transition_mode()
        response = self.client.maintenance_mode.status()
        self.assertTrue(len(response.activation_requested_at) > 0)

    def test_requested_by_secured(self):
        with mock.patch('manager_rest.resources_v2_1.'
                        '_prepare_maintenance_dict',
                        new=self.mock_prepare_maintenance_dict):
            self._activate_maintenance_mode()
            response = self.client.maintenance_mode.status()
            self.assertEqual(response.requested_by, 'mock user')

    def test_requested_by_non_secured(self):
        self._activate_maintenance_mode()
        response = self.client.maintenance_mode.status()
        self.assertTrue(len(response.requested_by) == 0)

    def test_deactivate_maintenance_mode(self):
        self._activate_maintenance_mode()
        response = self.client.maintenance_mode.deactivate()
        self.assertEqual(NOT_IN_MAINTENANCE_MODE, response.status)
        response = self.client.maintenance_mode.status()
        self.assertEqual(NOT_IN_MAINTENANCE_MODE, response.status)

    def test_request_approval_after_maintenance_mode_deactivation(self):
        self._activate_and_deactivate_maintenance_mode()
        self.client.blueprints.upload(
                self.get_mock_blueprint_path(),
                blueprint_id='b1')
        self.client.deployments.create('b1', 'd1')

    def test_multiple_maintenance_mode_deactivations(self):
        self._activate_and_deactivate_maintenance_mode()
        try:
            self.client.maintenance_mode.deactivate()
            self.fail('Expected the second stop request to fail '
                      'since maintenance mode is not active.')
        except exceptions.NotModifiedError as e:
            self.assertEqual(304, e.status_code)
        self.assertTrue('already deactivated' in e.message)

    def test_maintenance_file(self):
        maintenance_file = os.path.join(self.maintenance_mode_dir,
                                        MAINTENANCE_MODE_STATUS_FILE)

        self.assertFalse(os.path.isfile(maintenance_file))
        state = {'status': ACTIVATING_MAINTENANCE_MODE,
                 'activated_at': 'test 444'}

        utils.write_dict_to_json_file(maintenance_file, state)
        current_state = utils.read_json_file(maintenance_file)
        self.assertEqual(ACTIVATING_MAINTENANCE_MODE, current_state['status'])
        self.assertEqual('test 444', current_state['activated_at'])

        lst = ['1', 'b']
        state['status'] = MAINTENANCE_MODE_ACTIVE
        state['executions'] = lst
        utils.write_dict_to_json_file(maintenance_file, state)
        current_state = utils.read_json_file(maintenance_file)
        self.assertEqual(MAINTENANCE_MODE_ACTIVE, current_state['status'])
        self.assertEqual('test 444', current_state['activated_at'])
        self.assertEqual(lst, current_state['executions'])

    def test_maintenance_mode_active_error_raised(self):
        self._activate_maintenance_mode()
        self.assertRaises(exceptions.MaintenanceModeActiveError,
                          self.client.blueprints.list)

    def test_maintenance_mode_activating_error_raised(self):
        self.client.blueprints.upload(
                self.get_mock_blueprint_path(),
                blueprint_id='b1')
        self._start_maintenance_transition_mode()
        self.assertRaises(exceptions.MaintenanceModeActivatingError,
                          self.client.deployments.create,
                          blueprint_id='b1',
                          deployment_id='d1')

    def _activate_maintenance_mode(self):
        self.client.maintenance_mode.activate()
        self.client.maintenance_mode.status()

    def _start_maintenance_transition_mode(self):
        (blueprint_id, deployment_id, blueprint_response,
         deployment_response) = self.put_deployment('transition')
        execution = self.client.executions.start(deployment_id, 'install')
        execution = self.client.executions.get(execution.id)
        self.assertEquals('terminated', execution.status)
        storage_manager._get_instance().update_execution_status(
                execution.id, models.Execution.STARTED, error='')

        self.client.maintenance_mode.activate()
        response = self.client.maintenance_mode.status()
        self.assertEqual(ACTIVATING_MAINTENANCE_MODE, response.status)

        return execution

    def _terminate_execution(self, execution_id):
        storage_manager._get_instance().update_execution_status(
                execution_id, models.Execution.TERMINATED, error='')

    def _activate_and_deactivate_maintenance_mode(self):
        self._activate_maintenance_mode()
        self.client.maintenance_mode.deactivate()

    def mock_prepare_maintenance_dict(self,
                                      status,
                                      activated_at='',
                                      activation_requested_at='',
                                      remaining_executions=None,
                                      **_):
        state = {'status': status,
                 'activated_at': activated_at,
                 'activation_requested_at': activation_requested_at,
                 'remaining_executions': remaining_executions,
                 'requested_by': 'mock user'}
        return state
