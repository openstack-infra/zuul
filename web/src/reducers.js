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

// Redux store enable to share global variables through state
// To update the store, use a reducer and dispatch method,
// see the App.setTenant method
//
// The store contains:
//   info: the info object, tenant is set when white-label api
//   tenant: the current tenant name, only used with multi-tenant api

import { applyMiddleware, createStore, combineReducers } from 'redux'
import thunk from 'redux-thunk'

import { fetchConfigErrors, fetchInfo } from './api'

const infoReducer = (state = {}, action) => {
  switch (action.type) {
    case 'FETCH_INFO_SUCCESS':
      return action.info
    default:
      return state
  }
}

const configErrorsReducer = (state = [], action) => {
  switch (action.type) {
    case 'FETCH_CONFIGERRORS_SUCCESS':
      return action.errors
    default:
      return state
  }
}

const tenantReducer = (state = {}, action) => {
  switch (action.type) {
    case 'SET_TENANT':
      return action.tenant
    default:
      return state
  }
}

function createZuulStore() {
  return createStore(combineReducers({
    info: infoReducer,
    tenant: tenantReducer,
    configErrors: configErrorsReducer,
  }), applyMiddleware(thunk))
}

// Reducer actions
function fetchInfoAction () {
  return (dispatch) => {
    return fetchInfo()
      .then(response => {
        dispatch({type: 'FETCH_INFO_SUCCESS', info: response.data.info})
      })
      .catch(error => {
        throw (error)
      })
  }
}
function fetchConfigErrorsAction (tenant) {
  return (dispatch) => {
    return fetchConfigErrors(tenant.apiPrefix)
      .then(response => {
        dispatch({type: 'FETCH_CONFIGERRORS_SUCCESS',
                  errors: response.data})
      })
      .catch(error => {
        throw (error)
      })
  }
}

function setTenantAction (name, whiteLabel) {
  let apiPrefix = ''
  let linkPrefix = ''
  let routePrefix = ''
  let defaultRoute = '/status'
  if (!whiteLabel) {
    apiPrefix = 'tenant/' + name + '/'
    linkPrefix = '/t/' + name
    routePrefix = '/t/:tenant'
    defaultRoute = '/tenants'
  }
  return {
    type: 'SET_TENANT',
    tenant: {
      name: name,
      whiteLabel: whiteLabel,
      defaultRoute: defaultRoute,
      linkPrefix: linkPrefix,
      apiPrefix: apiPrefix,
      routePrefix: routePrefix
    }
  }
}

export {
  createZuulStore,
  setTenantAction,
  fetchConfigErrorsAction,
  fetchInfoAction
}
