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
  CHANGE_FETCH_FAIL,
  CHANGE_FETCH_REQUEST,
  CHANGE_FETCH_SUCCESS
} from '../actions/change'

export default (state = {
  isFetching: false,
  change: null
}, action) => {
  switch (action.type) {
    case CHANGE_FETCH_REQUEST:
      return {
        isFetching: true,
        change: state.change
      }
    case CHANGE_FETCH_SUCCESS:
      return {
        isFetching: false,
        change: action.change,
      }
    case CHANGE_FETCH_FAIL:
      return {
        isFetching: false,
        change: state.change,
      }
    default:
      return state
  }
}
