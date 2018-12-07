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

import * as API from '../api'

export const TENANTS_FETCH_REQUEST = 'TENANTS_FETCH_REQUEST'
export const TENANTS_FETCH_SUCCESS = 'TENANTS_FETCH_SUCCESS'
export const TENANTS_FETCH_FAIL = 'TENANTS_FETCH_FAIL'

export const requestTenants = () => ({
  type: TENANTS_FETCH_REQUEST
})

export const receiveTenants = json => ({
  type: TENANTS_FETCH_SUCCESS,
  tenants: json,
  receivedAt: Date.now()
})

const failedTenants = error => ({
  type: TENANTS_FETCH_FAIL,
  error
})

const fetchTenants = () => dispatch => {
  dispatch(requestTenants())
  return API.fetchTenants()
    .then(response => dispatch(receiveTenants(response.data)))
    .catch(error => dispatch(failedTenants(error)))
}

const shouldFetchTenants = state => {
  const tenants = state.tenants
  if (tenants.tenants.length > 0) {
    return false
  }
  if (tenants.isFetching) {
    return false
  }
  return true
}

export const fetchTenantsIfNeeded = (force) => (dispatch, getState) => {
  if (force || shouldFetchTenants(getState())) {
    return dispatch(fetchTenants())
  }
}
