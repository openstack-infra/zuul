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
} from 'patternfly-react'

import { fetchChangeStatus } from '../api'
import ChangePanel from '../containers/status/ChangePanel'


class ChangeStatusPage extends React.Component {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  state = {
    change: null,
    error: null,
  }

  updateData = () => {
    // Clear any running timer
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    this.setState({error: null})
    fetchChangeStatus(
      this.props.tenant.apiPrefix, this.props.match.params.changeId)
      .then(response => {
        this.setState({change: response.data})
      }).catch(error => {
        this.setState({error: error.message, change: null})
      })
    this.timer = setTimeout(this.updateData, 5000)
  }

  componentDidMount () {
    document.title = this.props.match.params.changeId + ' | Zuul Status'
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name) {
      this.updateData()
    }
  }

  componentWillUnmount () {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  render () {
    const { error, change } = this.state
    if (error) {
      return (<Alert>{this.state.error}</Alert>)
    }
    return (
      <React.Fragment>
        {change && change.map((item, idx) => (
          <div className='row' key={idx}>
            <ChangePanel
              globalExpanded={true}
              change={item}
              />
          </div>
        ))}
      </React.Fragment>)
  }
}

export default connect(state => ({tenant: state.tenant}))(ChangeStatusPage)
