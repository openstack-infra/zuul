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
  JOB_FETCH_FAIL,
  JOB_FETCH_REQUEST,
  JOB_FETCH_SUCCESS
} from '../actions/job'

import update from 'immutability-helper'

export default (state = {
  isFetching: false,
  jobs: {},
}, action) => {
  switch (action.type) {
    case JOB_FETCH_REQUEST:
      return {
        isFetching: true,
        jobs: state.jobs,
      }
    case JOB_FETCH_SUCCESS:
      if (!state.jobs[action.tenant]) {
        state.jobs = update(state.jobs, {$merge: {[action.tenant]: {}}})
      }
      return {
        isFetching: false,
        jobs: update(state.jobs, {
          [action.tenant]: {
            $merge: {
              [action.jobname]: action.job
            }
          }
        })
      }
    case JOB_FETCH_FAIL:
      return {
        isFetching: false,
        jobs: state.jobs,
      }
    default:
      return state
  }
}
