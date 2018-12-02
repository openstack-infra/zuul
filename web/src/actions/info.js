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

export const INFO_FETCH_REQUEST = 'INFO_FETCH_REQUEST'
export const INFO_FETCH_SUCCESS = 'INFO_FETCH_SUCCESS'
export const INFO_FETCH_FAIL    = 'INFO_FETCH_FAIL'

export const fetchInfoRequest = () => ({
  type: INFO_FETCH_REQUEST
})

export const fetchInfoSuccess = json => ({
  type: INFO_FETCH_SUCCESS,
  tenant: json.info.tenant,
})

const fetchInfoFail = error => ({
  type: INFO_FETCH_FAIL,
  error
})

const fetchInfo = () => dispatch => {
  dispatch(fetchInfoRequest())
  return API.fetchInfo()
    .then(response => dispatch(fetchInfoSuccess(response.data)))
    .catch(error => {
      dispatch(fetchInfoFail(error))
      setTimeout(() => {dispatch(fetchInfo())}, 5000)
    })
}

const shouldFetchInfo = state => {
  const info = state.info
  if (!info) {
    return true
  }
  if (info.isFetching) {
    return false
  }
  return true
}

export const fetchInfoIfNeeded = () => (dispatch, getState) => {
  if (shouldFetchInfo(getState())) {
    return dispatch(fetchInfo())
  }
}
