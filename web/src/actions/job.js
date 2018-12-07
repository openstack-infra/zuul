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

export const JOB_FETCH_REQUEST = 'JOB_FETCH_REQUEST'
export const JOB_FETCH_SUCCESS = 'JOB_FETCH_SUCCESS'
export const JOB_FETCH_FAIL = 'JOB_FETCH_FAIL'

export const requestJob = () => ({
  type: JOB_FETCH_REQUEST
})

export const receiveJob = (tenant, jobname, json) => ({
  type: JOB_FETCH_SUCCESS,
  tenant: tenant,
  jobname: jobname,
  job: json,
  receivedAt: Date.now()
})

const failedJob = error => ({
  type: JOB_FETCH_FAIL,
  error
})

const fetchJob = (tenant, jobname) => dispatch => {
  dispatch(requestJob())
  return API.fetchJob(tenant.apiPrefix, jobname)
    .then(response => dispatch(receiveJob(tenant.name, jobname, response.data)))
    .catch(error => dispatch(failedJob(error)))
}

const shouldFetchJob = (tenant, jobname, state) => {
  const tenantJobs = state.job.jobs[tenant.name]
  if (tenantJobs) {
    const job = tenantJobs[jobname]
    if (!job) {
      return true
    }
    if (job.isFetching) {
      return false
    }
    return false
  }
  return true
}

export const fetchJobIfNeeded = (tenant, jobname, force) => (
  dispatch, getState) => {
    if (force || shouldFetchJob(tenant, jobname, getState())) {
      return dispatch(fetchJob(tenant, jobname))
    }
    return Promise.resolve()
}
