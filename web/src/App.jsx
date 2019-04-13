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
import {
  Icon,
  Masthead,
  Notification,
  NotificationDrawer,
  TimedToastNotification,
  ToastNotificationList,
} from 'patternfly-react'
import * as moment from 'moment'

import ErrorBoundary from './containers/ErrorBoundary'
import logo from './images/logo.png'
import { routes } from './routes'
import { fetchConfigErrorsAction } from './actions/configErrors'
import { setTenantAction } from './actions/tenant'
import { clearError } from './actions/errors'


class App extends React.Component {
  static propTypes = {
    errors: PropTypes.array,
    configErrors: PropTypes.array,
    info: PropTypes.object,
    tenant: PropTypes.object,
    location: PropTypes.object,
    history: PropTypes.object,
    dispatch: PropTypes.func
  }

  state = {
    menuCollapsed: true,
    showErrors: false
  }

  onNavToggleClick = () => {
    this.setState({
      menuCollapsed: !this.state.menuCollapsed
    })
  }

  onNavClick = () => {
    this.setState({
      menuCollapsed: true
    })
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
            <Link
              to={this.props.tenant.linkPrefix + item.to}
              onClick={this.onNavClick}>
              {item.title}
            </Link>
          </li>
        ))}
      </ul>
    )
  }

  renderContent = () => {
    const { info, tenant } = this.props
    const allRoutes = []

    if (info.isFetching) {
      return (<h2>Fetching info...</h2>)
    }
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
    if (tenant.defaultRoute)
      allRoutes.push(
        <Redirect from='*' to={tenant.defaultRoute} key='default-route' />
      )
    return (
      <Switch>
        {allRoutes}
      </Switch>
    )
  }

  componentDidUpdate() {
    // This method is called when info property is updated
    const { tenant, info } = this.props
    if (info.ready) {
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
        }
      }
      // Set tenant only if it changed to prevent DidUpdate loop
      if (tenant.name !== tenantName) {
        const tenantAction = setTenantAction(tenantName, whiteLabel)
        this.props.dispatch(tenantAction)
        if (tenantName) {
          this.props.dispatch(fetchConfigErrorsAction(tenantAction.tenant))
        }
      }
    }
  }

  renderErrors = (errors) => {
    return (
      <ToastNotificationList>
        {errors.map(error => (
         <TimedToastNotification
             key={error.id}
             type='error'
             onDismiss={() => {this.props.dispatch(clearError(error.id))}}
             >
           <span title={moment(error.date).format()}>
               <strong>{error.text}</strong> ({error.status})&nbsp;
                   {error.url}
             </span>
         </TimedToastNotification>
        ))}
      </ToastNotificationList>
    )
  }

  renderConfigErrors = (configErrors) => {
    const { history } = this.props
    const errors = []
    configErrors.forEach((item, idx) => {
      let error = item.error
      let cookie = error.indexOf('The error was:')
      if (cookie !== -1) {
        error = error.slice(cookie + 18).split('\n')[0]
      }
      let ctxPath = item.source_context.path
      if (item.source_context.branch !== 'master') {
        ctxPath += ' (' + item.source_context.branch + ')'
      }
      errors.push(
        <Notification
          key={idx}
          seen={false}
          onClick={() => {
            history.push(this.props.tenant.linkPrefix + '/config-errors')
            this.setState({showErrors: false})
          }}
          >
          <Icon className='pull-left' type='pf' name='error-circle-o' />
          <Notification.Content>
            <Notification.Message>
              {error}
            </Notification.Message>
            <Notification.Info
              leftText={item.source_context.project}
              rightText={ctxPath}
              />
          </Notification.Content>
        </Notification>
      )
    })
    return (
      <NotificationDrawer style={{minWidth: '500px'}}>
      <NotificationDrawer.Panel>
        <NotificationDrawer.PanelHeading>
          <NotificationDrawer.PanelTitle>
            Config Errors
          </NotificationDrawer.PanelTitle>
          <NotificationDrawer.PanelCounter
            text={errors.length + ' error(s)'} />
        </NotificationDrawer.PanelHeading>
        <NotificationDrawer.PanelCollapse id={1} collapseIn>
          <NotificationDrawer.PanelBody key='containsNotifications'>
            {errors.map(item => (item))}
          </NotificationDrawer.PanelBody>

        </NotificationDrawer.PanelCollapse>
        </NotificationDrawer.Panel>
      </NotificationDrawer>
    )
  }

  render() {
    const { menuCollapsed, showErrors } = this.state
    const { errors, configErrors, tenant } = this.props

    return (
      <React.Fragment>
        <Masthead
          iconImg={logo}
          onNavToggleClick={this.onNavToggleClick}
          navToggle
          thin
          >
          <div className='collapse navbar-collapse'>
            {tenant.name && this.renderMenu()}
            <ul className='nav navbar-nav navbar-utility'>
              { configErrors.length > 0 &&
                <NotificationDrawer.Toggle
                  className="zuul-config-errors"
                  hasUnreadMessages
                  style={{color: 'orange'}}
                  onClick={(e) => {
                    e.preventDefault()
                    this.setState({showErrors: !this.state.showErrors})}}
                  />
              }
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
            {showErrors && this.renderConfigErrors(configErrors)}
          </div>
          {!menuCollapsed && (
            <div className='collapse navbar-collapse navbar-collapse-1 in'>
              {tenant.name && this.renderMenu()}
            </div>
          )}
        </Masthead>
        {errors.length > 0 && this.renderErrors(errors)}
        <div className='container-fluid container-cards-pf'>
          <ErrorBoundary>
            {this.renderContent()}
          </ErrorBoundary>
        </div>
      </React.Fragment>
    )
  }
}

// This connect the info state from the store to the info property of the App.
export default withRouter(connect(
  state => ({
    errors: state.errors,
    configErrors: state.configErrors,
    info: state.info,
    tenant: state.tenant
  })
)(App))
