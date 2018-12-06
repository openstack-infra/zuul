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

import {
  TENANTS_FETCH_FAIL,
  TENANTS_FETCH_REQUEST,
  TENANTS_FETCH_SUCCESS
} from '../actions/tenants'

export default (state = {
  isFetching: false,
  tenants: []
}, action) => {
  switch (action.type) {
    case TENANTS_FETCH_REQUEST:
      return {
        isFetching: true,
        tenants: state.tenants
      }
    case TENANTS_FETCH_SUCCESS:
      return {
        isFetching: false,
        tenants: action.tenants,
      }
    case TENANTS_FETCH_FAIL:
      return {
        isFetching: false,
        tenants: state.tenants,
      }
    default:
      return state
  }
}
