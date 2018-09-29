/* global setTimeout, clearTimeout */
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

import * as React from 'react'
import PropTypes from 'prop-types'
import { connect } from 'react-redux'
import {
  Alert,
  Checkbox,
  Icon,
  Form,
  FormGroup,
  FormControl,
  Spinner
} from 'patternfly-react'

import { fetchStatus } from '../api'
import Pipeline from '../containers/status/Pipeline'


class StatusPage extends React.Component {
  static propTypes = {
    location: PropTypes.object,
    tenant: PropTypes.object
  }

  state = {
    status: null,
    filter: null,
    expanded: false,
    error: null,
    loading: false,
    autoReload: true
  }

  visibilityListener = () => {
    if (document[this.visibilityStateProperty] === 'visible') {
      this.visible = true
      this.updateData()
    } else {
      this.visible = false
    }
  }

  constructor () {
    super()

    this.timer = null
    this.visible = true

    // Stop refresh when page is not visible
    if (typeof document.hidden !== 'undefined') {
      this.visibilityChangeEvent = 'visibilitychange'
      this.visibilityStateProperty = 'visibilityState'
    } else if (typeof document.mozHidden !== 'undefined') {
      this.visibilityChangeEvent = 'mozvisibilitychange'
      this.visibilityStateProperty = 'mozVisibilityState'
    } else if (typeof document.msHidden !== 'undefined') {
      this.visibilityChangeEvent = 'msvisibilitychange'
      this.visibilityStateProperty = 'msVisibilityState'
    } else if (typeof document.webkitHidden !== 'undefined') {
      this.visibilityChangeEvent = 'webkitvisibilitychange'
      this.visibilityStateProperty = 'webkitVisibilityState'
    }
    document.addEventListener(
      this.visibilityChangeEvent, this.visibilityListener, false)
  }

  setCookie (name, value) {
    document.cookie = name + '=' + value + '; path=/'
  }

  updateData = (force) => {
    /* // Create fake delay
    function sleeper(ms) {
      return function(x) {
        return new Promise(resolve => setTimeout(() => resolve(x), ms));
      };
    }
    */

    if (force || (this.visible && this.state.autoReload)) {
      this.setState({error: null, loading: true})
      fetchStatus(this.props.tenant.apiPrefix)
        // .then(sleeper(2000))
        .then(response => {
          this.setState({status: response.data, loading: false})
        }).catch(error => {
          this.setState({error: error.message, status: null})
        })
    }
    // Clear any running timer
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (this.state.autoReload) {
      this.timer = setTimeout(this.updateData, 5000)
    }
  }

  componentDidMount () {
    document.title = 'Zuul Status'
    this.loadState()
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps, prevState) {
    // When autoReload is set, also call updateData to retrigger the setTimeout
    if (this.props.tenant.name !== prevProps.tenant.name || (
        this.state.autoReload &&
       this.state.autoReload !== prevState.autoReload)) {
      this.updateData()
    }
  }

  componentWillUnmount () {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    document.removeEventListener(
      this.visibilityChangeEvent, this.visibilityListener)
  }

  setFilter = (filter) => {
    this.filter.value = filter
    this.setState({filter: filter})
    this.setCookie('zuul_filter_string', filter)
  }

  handleKeyPress = (e) => {
    if (e.charCode === 13) {
      this.setFilter(e.target.value)
      e.preventDefault()
      e.target.blur()
    }
  }

  handleCheckBox = (e) => {
    this.setState({expanded: e.target.checked})
    this.setCookie('zuul_expand_by_default', e.target.checked)
  }

  loadState = () => {
    function readCookie (name, defaultValue) {
      let nameEQ = name + '='
      let ca = document.cookie.split(';')
      for (let i = 0; i < ca.length; i++) {
        let c = ca[i]
        while (c.charAt(0) === ' ') {
          c = c.substring(1, c.length)
        }
        if (c.indexOf(nameEQ) === 0) {
          return c.substring(nameEQ.length, c.length)
        }
      }
      return defaultValue
    }
    let filter = readCookie('zuul_filter_string', '')
    let expanded = readCookie('zuul_expand_by_default', false)
    if (typeof expanded === 'string') {
      expanded = (expanded === 'true')
    }

    if (this.props.location.hash) {
      filter = this.props.location.hash.slice(1)
    }
    if (filter || expanded) {
      this.setState({
        filter: filter,
        expanded: expanded
      })
    }
  }

  renderStatusHeader (status) {
    return (
      <p>
        Queue lengths: <span>{status.trigger_event_queue ?
                              status.trigger_event_queue.length : '0'
          }</span> events,
        <span>{status.management_event_queue ?
               status.management_event_queue.length : '0'
          }</span> management events,
        <span>{status.result_event_queue ?
               status.result_event_queue.length : '0'
          }</span> results.
      </p>
    )
  }

  renderStatusFooter (status) {
    return (
      <React.Fragment>
        <p>Zuul version: <span>{status.zuul_version}</span></p>
        {status.last_reconfigured ? (
          <p>Last reconfigured: <span>
              {new Date(status.last_reconfigured).toString()}
          </span></p>) : ''}
      </React.Fragment>
    )
  }

  render () {
    const { autoReload, error, status, filter, expanded, loading } = this.state
    if (error) {
      return (<Alert>{this.state.error}</Alert>)
    }
    if (this.filter && filter) {
      this.filter.value = filter
    }
    const statusControl = (
      <Form inline>
        <FormGroup controlId='status'>
          <FormControl
            type='text'
            placeholder='change or project name'
            defaultValue={filter}
            inputRef={i => this.filter = i}
            onKeyPress={this.handleKeyPress} />
            {filter && (
          <FormControl.Feedback>
            <span
              onClick={() => {this.setFilter('')}}
              style={{cursor: 'pointer', zIndex: 10, pointerEvents: 'auto'}}
              >
              <Icon type='pf' title='Clear filter' name='delete' />
              &nbsp;
            </span>
          </FormControl.Feedback>
            )}
        </FormGroup>
        <FormGroup controlId='status'>
          &nbsp; Expand by default:&nbsp;
          <Checkbox
            defaultChecked={expanded}
            onChange={this.handleCheckBox} />
        </FormGroup>
      </Form>
    )
    return (
      <React.Fragment>
        <div className="pull-right" style={{display: 'flex'}}>
          <Spinner loading={loading}>
            <a className="refresh" onClick={() => {this.updateData(true)}}>
              <Icon type="fa" name="refresh" /> refresh&nbsp;&nbsp;
            </a>
          </Spinner>
          <Checkbox
            defaultChecked={autoReload}
            onChange={(e) => {this.setState({autoReload: e.target.checked})}}
            style={{marginTop: '0px'}}>
            auto reload
          </Checkbox>
        </div>

        {status && this.renderStatusHeader(status)}
        {statusControl}
        <div className='row'>
          {status && status.pipelines.map(item => (
            <Pipeline
              pipeline={item}
              filter={filter}
              expanded={expanded}
              key={item.name}
              />
          ))}
        </div>
        {status && this.renderStatusFooter(status)}
      </React.Fragment>)
  }
}

export default connect(state => ({tenant: state.tenant}))(StatusPage)
