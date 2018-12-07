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

export const JOBS_FETCH_REQUEST = 'JOBS_FETCH_REQUEST'
export const JOBS_FETCH_SUCCESS = 'JOBS_FETCH_SUCCESS'
export const JOBS_FETCH_FAIL = 'JOBS_FETCH_FAIL'

export const requestJobs = () => ({
  type: JOBS_FETCH_REQUEST
})

export const receiveJobs = (tenant, json) => ({
  type: JOBS_FETCH_SUCCESS,
  tenant: tenant,
  jobs: json,
  receivedAt: Date.now()
})

const failedJobs = error => ({
  type: JOBS_FETCH_FAIL,
  error
})

const fetchJobs = (tenant) => dispatch => {
  dispatch(requestJobs())
  return API.fetchJobs(tenant.apiPrefix)
    .then(response => dispatch(receiveJobs(tenant.name, response.data)))
    .catch(error => dispatch(failedJobs(error)))
}

const shouldFetchJobs = (tenant, state) => {
  const jobs = state.jobs.jobs[tenant.name]
  if (!jobs || jobs.length === 0) {
    return true
  }
  if (jobs.isFetching) {
    return false
  }
  return false
}

export const fetchJobsIfNeeded = (tenant, force) => (dispatch, getState) => {
  if (force || shouldFetchJobs(tenant, getState())) {
    return dispatch(fetchJobs(tenant))
  }
  return Promise.resolve()
}
