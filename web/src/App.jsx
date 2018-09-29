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

// The App is the parent component of every pages. Each page content is
// rendered by the Route object according to the current location.

import React from 'react'
import PropTypes from 'prop-types'
import { matchPath, withRouter } from 'react-router'
import { Link, Redirect, Route, Switch } from 'react-router-dom'
import { connect } from 'react-redux'
import { Masthead } from 'patternfly-react'

import logo from './images/logo.png'
import { routes } from './routes'
import { setTenantAction } from './reducers'


class App extends React.Component {
  static propTypes = {
    info: PropTypes.object,
    tenant: PropTypes.object,
    location: PropTypes.object,
    dispatch: PropTypes.func
  }

  constructor() {
    super()
    this.menu = routes()
  }

  renderMenu() {
    const { location } = this.props
    const activeItem = this.menu.find(
      item => location.pathname === item.to
    )
    return (
      <ul className='nav navbar-nav navbar-primary'>
        {this.menu.filter(item => item.title).map(item => (
          <li key={item.to} className={item === activeItem ? 'active' : ''}>
            <Link to={this.props.tenant.linkPrefix + item.to}>
              {item.title}
            </Link>
          </li>
        ))}
      </ul>
    )
  }

  renderContent = () => {
    const { tenant } = this.props
    const allRoutes = []
    this.menu
      // Do not include '/tenants' route in white-label setup
      .filter(item =>
              (tenant.whiteLabel && !item.globalRoute) || !tenant.whiteLabel)
      .forEach((item, index) => {
        allRoutes.push(
          <Route
            key={index}
            path={item.globalRoute ? item.to : tenant.routePrefix + item.to}
            component={item.component}
            exact
            />
        )
    })
    return (
      <Switch>
        {allRoutes}
        <Redirect from='*' to={tenant.defaultRoute} key='default-route' />
      </Switch>
    )
  }

  componentDidUpdate() {
    // This method is called when info property is updated
    const { tenant, info } = this.props
    if (info.capabilities) {
      let tenantName, whiteLabel

      if (info.tenant) {
        // White label
        whiteLabel = true
        tenantName = info.tenant
      } else if (!info.tenant) {
        // Multi tenant, look for tenant name in url
        whiteLabel = false

        const match = matchPath(
          this.props.location.pathname, {path: '/t/:tenant'})

        if (match) {
          tenantName = match.params.tenant
        } else {
          tenantName = ''
        }
      }
      // Set tenant only if it changed to prevent DidUpdate loop
      if (typeof tenant.name === 'undefined' || tenant.name !== tenantName) {
        this.props.dispatch(setTenantAction(tenantName, whiteLabel))
      }
    }
  }

  render() {
    const { tenant } = this.props
    if (typeof tenant.name === 'undefined') {
      return (<h2>Loading...</h2>)
    }

    return (
      <React.Fragment>
        <Masthead
          iconImg={logo}
          navToggle
          thin
          >
          <div className='collapse navbar-collapse'>
            {tenant.name && this.renderMenu()}
            <ul className='nav navbar-nav navbar-utility'>
              <li>
                <a href='https://zuul-ci.org/docs'
                   rel='noopener noreferrer' target='_blank'>
                  Documentation
                </a>
              </li>
              {tenant.name && (
                <li>
                  <Link to={tenant.defaultRoute}>
                    <strong>Tenant</strong> {tenant.name}
                  </Link>
                </li>
              )}
            </ul>
          </div>
        </Masthead>
        <div className='container-fluid container-cards-pf'>
          {this.renderContent()}
        </div>
      </React.Fragment>
    )
  }
}

// This connect the info state from the store to the info property of the App.
export default withRouter(connect(
  state => ({
    info: state.info,
    tenant: state.tenant
  })
)(App))
