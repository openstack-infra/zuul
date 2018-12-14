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

export const PROJECT_FETCH_REQUEST = 'PROJECT_FETCH_REQUEST'
export const PROJECT_FETCH_SUCCESS = 'PROJECT_FETCH_SUCCESS'
export const PROJECT_FETCH_FAIL = 'PROJECT_FETCH_FAIL'

export const requestProject = () => ({
  type: PROJECT_FETCH_REQUEST
})

export const receiveProject = (tenant, projectName, project) => {
  // TODO: fix api to return template name or merge them
  // in the mean-time, merge the jobs in project configs
  const templateIdx = []
  let idx
  project.configs.forEach((config, idx) => {
    if (config.default_branch === null) {
      // This must be a template
      templateIdx.push(idx)
      config.pipelines.forEach(templatePipeline => {
        let pipeline = project.configs[idx - 1].pipelines.filter(
          item => item.name === templatePipeline.name)
        if (pipeline.length === 0) {
          // Pipeline doesn't exist in project config
          project.configs[idx - 1].pipelines.push(templatePipeline)
        } else {
          if (pipeline[0].queue_name === null) {
            pipeline[0].queue_name = templatePipeline.queue_name
          }
          templatePipeline.jobs.forEach(job => {
            pipeline[0].jobs.push(job)
          })
        }
      })
    }
  })
  for (idx = templateIdx.length - 1; idx >= 0; idx -= 1) {
    project.configs.splice(templateIdx[idx], 1)
  }

  return {
    type: PROJECT_FETCH_SUCCESS,
    tenant: tenant,
    projectName: projectName,
    project: project,
    receivedAt: Date.now(),
  }
}

const failedProject = error => ({
  type: PROJECT_FETCH_FAIL,
  error
})

const fetchProject = (tenant, project) => dispatch => {
  dispatch(requestProject())
  return API.fetchProject(tenant.apiPrefix, project)
    .then(response => dispatch(receiveProject(
      tenant.name, project, response.data)))
    .catch(error => dispatch(failedProject(error)))
}

const shouldFetchProject = (tenant, projectName, state) => {
  const tenantProjects = state.project.projects[tenant.name]
  if (tenantProjects) {
    const project = tenantProjects[projectName]
    if (!project) {
      return true
    }
    if (project.isFetching) {
      return false
    }
    return false
  }
  return true
}

export const fetchProjectIfNeeded = (tenant, project, force) => (
  dispatch, getState) => {
    if (force || shouldFetchProject(tenant, project, getState())) {
      return dispatch(fetchProject(tenant, project))
    }
    return Promise.resolve()
}
