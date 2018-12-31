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

export const CHANGE_FETCH_REQUEST = 'CHANGE_FETCH_REQUEST'
export const CHANGE_FETCH_SUCCESS = 'CHANGE_FETCH_SUCCESS'
export const CHANGE_FETCH_FAIL = 'CHANGE_FETCH_FAIL'

export const requestChange = () => ({
  type: CHANGE_FETCH_REQUEST
})

export const receiveChange = json => ({
  type: CHANGE_FETCH_SUCCESS,
  change: json,
  receivedAt: Date.now()
})

const failedChange = error => ({
  type: CHANGE_FETCH_FAIL,
  error
})

const fetchChange = (tenant, changeId) => dispatch => {
  dispatch(requestChange())
  return API.fetchChangeStatus(tenant.apiPrefix, changeId)
    .then(response => dispatch(receiveChange(response.data)))
    .catch(error => dispatch(failedChange(error)))
}

const shouldFetchChange = state => {
  const change = state.change
  if (!change) {
    return true
  }
  if (change.isFetching) {
    return false
  }
  return true
}

export const fetchChangeIfNeeded = (tenant, change, force) => (
  dispatch, getState) => {
    if (force || shouldFetchChange(getState())) {
      return dispatch(fetchChange(tenant, change))
    }
    return Promise.resolve()
}
