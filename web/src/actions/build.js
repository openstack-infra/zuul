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

export const BUILD_FETCH_REQUEST = 'BUILD_FETCH_REQUEST'
export const BUILD_FETCH_SUCCESS = 'BUILD_FETCH_SUCCESS'
export const BUILD_FETCH_FAIL = 'BUILD_FETCH_FAIL'

export const requestBuild = () => ({
  type: BUILD_FETCH_REQUEST
})

export const receiveBuild = (buildId, build) => ({
  type: BUILD_FETCH_SUCCESS,
  buildId: buildId,
  build: build,
  receivedAt: Date.now()
})

const failedBuild = error => ({
  type: BUILD_FETCH_FAIL,
  error
})

const fetchBuild = (tenant, build) => dispatch => {
  dispatch(requestBuild())
  return API.fetchBuild(tenant.apiPrefix, build)
    .then(response => dispatch(receiveBuild(build, response.data)))
    .catch(error => dispatch(failedBuild(error)))
}

const shouldFetchBuild = (buildId, state) => {
  const build = state.build.builds[buildId]
  if (!build) {
    return true
  }
  if (build.isFetching) {
    return false
  }
  return false
}

export const fetchBuildIfNeeded = (tenant, buildId, force) => (
  dispatch, getState) => {
    if (force || shouldFetchBuild(buildId, getState())) {
      return dispatch(fetchBuild(tenant, buildId))
    }
}
