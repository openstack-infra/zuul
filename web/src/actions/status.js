/* global Promise */
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

export const STATUS_FETCH_REQUEST = 'STATUS_FETCH_REQUEST'
export const STATUS_FETCH_SUCCESS = 'STATUS_FETCH_SUCCESS'
export const STATUS_FETCH_FAIL = 'STATUS_FETCH_FAIL'

export const requestStatus = () => ({
  type: STATUS_FETCH_REQUEST
})

export const receiveStatus = json => ({
  type: STATUS_FETCH_SUCCESS,
  status: json,
  receivedAt: Date.now()
})

const failedStatus = error => ({
  type: STATUS_FETCH_FAIL,
  error
})

// Create fake delay
//function sleeper(ms) {
//  return function(x) {
//    return new Promise(resolve => setTimeout(() => resolve(x), ms));
//  };
//}

const fetchStatus = (tenant) => dispatch => {
  dispatch(requestStatus())
  return API.fetchStatus(tenant.apiPrefix)
    .then(response => dispatch(receiveStatus(response.data)))
    .catch(error => dispatch(failedStatus(error)))
}

const shouldFetchStatus = state => {
  const status = state.status
  if (!status) {
    return true
  }
  if (status.isFetching) {
    return false
  }
  return true
}

export const fetchStatusIfNeeded = (tenant) => (dispatch, getState) => {
  if (shouldFetchStatus(getState())) {
    return dispatch(fetchStatus(tenant))
  }
  return Promise.resolve()
}
