/* global expect, jest, it */
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

import React from 'react'
import ReactTestUtils from 'react-dom/test-utils'
import { Link, BrowserRouter as Router } from 'react-router-dom'
import { Provider } from 'react-redux'

import { setTenantAction } from '../../actions/tenant'
import createZuulStore from '../../store'
import ChangePanel from './ChangePanel'


const fakeChange = {
  project: 'org-project',
  jobs: [{
    name: 'job-name',
    url: 'stream/42',
    result: null
  }]
}

it('change panel render multi tenant links', () => {
  const store = createZuulStore()
  store.dispatch(setTenantAction('tenant-one', false))
  const application = ReactTestUtils.renderIntoDocument(
    <Provider store={store}>
      <Router>
        <ChangePanel change={fakeChange} globalExpanded={true} />
      </Router>
    </Provider>
  )
  const jobLink = ReactTestUtils.findRenderedComponentWithType(
    application, Link)
  expect(jobLink.props.to).toEqual(
    '/t/tenant-one/stream/42')
})

it('change panel render white-label tenant links', () => {
  const store = createZuulStore()
  store.dispatch(setTenantAction('tenant-one', true))
  const application = ReactTestUtils.renderIntoDocument(
    <Provider store={store}>
      <Router>
        <ChangePanel change={fakeChange} globalExpanded={true} />
      </Router>
    </Provider>
  )
  const jobLink = ReactTestUtils.findRenderedComponentWithType(
    application, Link)
  expect(jobLink.props.to).toEqual(
    '/stream/42')
})
