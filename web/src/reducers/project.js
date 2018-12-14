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

import {
  PROJECT_FETCH_FAIL,
  PROJECT_FETCH_REQUEST,
  PROJECT_FETCH_SUCCESS
} from '../actions/project'

import update from 'immutability-helper'

export default (state = {
  isFetching: false,
  projects: {},
}, action) => {
  switch (action.type) {
    case PROJECT_FETCH_REQUEST:
      return {
        isFetching: true,
        projects: state.projects,
      }
    case PROJECT_FETCH_SUCCESS:
      if (!state.projects[action.tenant]) {
        state.projects = update(state.projects, {$merge: {[action.tenant]: {}}})
      }
      return {
        isFetching: false,
        projects: update(state.projects, {
          [action.tenant]: {
            $merge: {
              [action.projectName]: action.project
            }
          }
        })
      }
    case PROJECT_FETCH_FAIL:
      return {
        isFetching: false,
        projects: state.projects,
      }
    default:
      return state
  }
}
