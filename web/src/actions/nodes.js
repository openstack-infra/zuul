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

export const NODES_FETCH_REQUEST = 'NODES_FETCH_REQUEST'
export const NODES_FETCH_SUCCESS = 'NODES_FETCH_SUCCESS'
export const NODES_FETCH_FAIL = 'NODES_FETCH_FAIL'

export const requestNodes = () => ({
  type: NODES_FETCH_REQUEST
})

export const receiveNodes = (tenant, json) => ({
  type: NODES_FETCH_SUCCESS,
  nodes: json,
  receivedAt: Date.now()
})

const failedNodes = error => ({
  type: NODES_FETCH_FAIL,
  error
})

const fetchNodes = (tenant) => dispatch => {
  dispatch(requestNodes())
  return API.fetchNodes(tenant.apiPrefix)
    .then(response => dispatch(receiveNodes(tenant.name, response.data)))
    .catch(error => dispatch(failedNodes(error)))
}

const shouldFetchNodes = (tenant, state) => {
  const nodes = state.nodes
  if (!nodes || nodes.nodes.length === 0) {
    return true
  }
  if (nodes.isFetching) {
    return false
  }
  if (Date.now() - nodes.receivedAt > 60000) {
    // Refetch after 1 minutes
    return true
  }
  return false
}

export const fetchNodesIfNeeded = (tenant, force) => (
  dispatch, getState) => {
    if (force || shouldFetchNodes(tenant, getState())) {
      return dispatch(fetchNodes(tenant))
    }
}
