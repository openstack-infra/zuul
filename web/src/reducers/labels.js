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
  LABELS_FETCH_FAIL,
  LABELS_FETCH_REQUEST,
  LABELS_FETCH_SUCCESS
} from '../actions/labels'

import update from 'immutability-helper'

export default (state = {
  isFetching: false,
  labels: {},
}, action) => {
  switch (action.type) {
    case LABELS_FETCH_REQUEST:
      return {
        isFetching: true,
        labels: state.labels,
      }
    case LABELS_FETCH_SUCCESS:
      return {
        isFetching: false,
        labels: update(
          state.labels, {$merge: {[action.tenant]: action.labels}}),
      }
    case LABELS_FETCH_FAIL:
      return {
        isFetching: false,
        labels: state.labels,
      }
    default:
      return state
  }
}
