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

import Axios from 'axios'

import * as API from '../api'

export const BUILD_FETCH_REQUEST = 'BUILD_FETCH_REQUEST'
export const BUILD_FETCH_SUCCESS = 'BUILD_FETCH_SUCCESS'
export const BUILD_FETCH_FAIL = 'BUILD_FETCH_FAIL'
export const BUILD_OUTPUT_FETCH_SUCCESS = 'BUILD_OUTPUT_FETCH_SUCCESS'

export const requestBuild = () => ({
  type: BUILD_FETCH_REQUEST
})

export const receiveBuild = (buildId, build) => ({
  type: BUILD_FETCH_SUCCESS,
  buildId: buildId,
  build: build,
  receivedAt: Date.now()
})

const receiveBuildOutput = (buildId, output) => {
  const hosts = {}
  // Compute stats
  output.forEach(phase => {
    Object.entries(phase.stats).forEach(([host, stats]) => {
      if (!hosts[host]) {
        hosts[host] = stats
        hosts[host].failed = []
      } else {
        hosts[host].changed += stats.changed
        hosts[host].failures += stats.failures
        hosts[host].ok += stats.ok
      }
      if (stats.failures > 0) {
        // Look for failed tasks
        phase.plays.forEach(play => {
          play.tasks.forEach(task => {
            if (task.hosts[host]) {
              if (task.hosts[host].results &&
                  task.hosts[host].results.length > 0) {
                task.hosts[host].results.forEach(result => {
                  if (result.failed) {
                    result.name = task.task.name
                    hosts[host].failed.push(result)
                  }
                })
              } else if (task.hosts[host].rc || task.hosts[host].failed) {
                let result = task.hosts[host]
                result.name = task.task.name
                hosts[host].failed.push(result)
              }
            }
          })
        })
      }
    })
  })
  return {
    type: BUILD_OUTPUT_FETCH_SUCCESS,
    buildId: buildId,
    output: hosts,
    receivedAt: Date.now()
  }
}

const failedBuild = error => ({
  type: BUILD_FETCH_FAIL,
  error
})

const fetchBuild = (tenant, build) => dispatch => {
  dispatch(requestBuild())
  return API.fetchBuild(tenant.apiPrefix, build)
    .then(response => {
      dispatch(receiveBuild(build, response.data))
      if (response.data.log_url) {
        const url = response.data.log_url.substr(
          0, response.data.log_url.lastIndexOf('/') + 1)
        Axios.get(url + 'job-output.json.gz')
          .then(response => dispatch(receiveBuildOutput(build, response.data)))
          .catch(error => {
            if (!error.request) {
              throw error
            }
            // Try without compression
            Axios.get(url + 'job-output.json')
              .then(response => dispatch(receiveBuildOutput(
                build, response.data)))
          })
          .catch(error => console.error(
            'Couldn\'t decode job-output...', error))
      }
    })
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
