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

export const LABELS_FETCH_REQUEST = 'LABELS_FETCH_REQUEST'
export const LABELS_FETCH_SUCCESS = 'LABELS_FETCH_SUCCESS'
export const LABELS_FETCH_FAIL = 'LABELS_FETCH_FAIL'

export const requestLabels = () => ({
  type: LABELS_FETCH_REQUEST
})

export const receiveLabels = (tenant, json) => ({
  type: LABELS_FETCH_SUCCESS,
  tenant: tenant,
  labels: json,
  receivedAt: Date.now()
})

const failedLabels = error => ({
  type: LABELS_FETCH_FAIL,
  error
})

const fetchLabels = (tenant) => dispatch => {
  dispatch(requestLabels())
  return API.fetchLabels(tenant.apiPrefix)
    .then(response => dispatch(receiveLabels(tenant.name, response.data)))
    .catch(error => dispatch(failedLabels(error)))
}

const shouldFetchLabels = (tenant, state) => {
  const labels = state.labels.labels[tenant.name]
  if (!labels || labels.length === 0) {
    return true
  }
  if (labels.isFetching) {
    return false
  }
  return false
}

export const fetchLabelsIfNeeded = (tenant, force) => (
  dispatch, getState) => {
    if (force || shouldFetchLabels(tenant, getState())) {
      return dispatch(fetchLabels(tenant))
    }
}
