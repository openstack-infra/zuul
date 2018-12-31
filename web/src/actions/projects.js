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

export const PROJECTS_FETCH_REQUEST = 'PROJECTS_FETCH_REQUEST'
export const PROJECTS_FETCH_SUCCESS = 'PROJECTS_FETCH_SUCCESS'
export const PROJECTS_FETCH_FAIL = 'PROJECTS_FETCH_FAIL'

export const requestProjects = () => ({
  type: PROJECTS_FETCH_REQUEST
})

export const receiveProjects = (tenant, json) => ({
  type: PROJECTS_FETCH_SUCCESS,
  tenant: tenant,
  projects: json,
  receivedAt: Date.now()
})

const failedProjects = error => ({
  type: PROJECTS_FETCH_FAIL,
  error
})

const fetchProjects = (tenant) => dispatch => {
  dispatch(requestProjects())
  return API.fetchProjects(tenant.apiPrefix)
    .then(response => dispatch(receiveProjects(tenant.name, response.data)))
    .catch(error => dispatch(failedProjects(error)))
}

const shouldFetchProjects = (tenant, state) => {
  const projects = state.projects.projects[tenant.name]
  if (!projects || projects.length === 0) {
    return true
  }
  if (projects.isFetching) {
    return false
  }
  return false
}

export const fetchProjectsIfNeeded = (tenant, force) => (
  dispatch, getState) => {
    if (force || shouldFetchProjects(tenant, getState())) {
      return dispatch(fetchProjects(tenant))
    }
    return Promise.resolve()
}
