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

import update from 'immutability-helper'

import {
  ADD_ERROR,
  CLEAR_ERROR,
  CLEAR_ERRORS,
  addApiError,
} from '../actions/errors'


export default (state = [], action) => {
  // Intercept API failure
  if (action.error && action.type.match(/.*_FETCH_FAIL$/)) {
    action = addApiError(action.error)
  }
  switch (action.type) {
    case ADD_ERROR:
      if (state.filter(error => (
            error.url === action.error.url &&
            error.status === action.error.status)).length > 0)
        return state
      action.error.id = action.id
      action.error.date = Date.now()
      return update(state, {$push: [action.error]})
    case CLEAR_ERROR:
      return update(state, {$splice: [[state.indexOf(
        state.filter(item => (item.id === action.id))[0]), 1]]})
    case CLEAR_ERRORS:
      return []
    default:
      return state
  }
}
