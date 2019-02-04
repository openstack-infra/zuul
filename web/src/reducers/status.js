// Copyright 2018 Red Hat, Inc
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License. You may obtain
// a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations
// under the License.

import { TENANT_SET } from '../actions/tenant'
import {
  STATUS_FETCH_FAIL,
  STATUS_FETCH_REQUEST,
  STATUS_FETCH_SUCCESS
} from '../actions/status'

export default (state = {
  isFetching: false,
  status: null
}, action) => {
  switch (action.type) {
    case TENANT_SET:
      return {
        isFetching: false,
        status: null,
      }
    case STATUS_FETCH_REQUEST:
      return {
        isFetching: true,
        status: state.status
      }
    case STATUS_FETCH_SUCCESS:
      return {
        isFetching: false,
        status: action.status,
      }
    case STATUS_FETCH_FAIL:
      return {
        isFetching: false,
        status: state.status,
      }
    default:
      return state
  }
}
