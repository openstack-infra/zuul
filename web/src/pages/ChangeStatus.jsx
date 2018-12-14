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

import { fetchChangeIfNeeded } from '../actions/change'
import ChangePanel from '../containers/status/ChangePanel'
import Refreshable from '../containers/Refreshable'


class ChangeStatusPage extends Refreshable {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object,
    remoteData: PropTypes.object,
    dispatch: PropTypes.func
  }

  updateData = (force) => {
    this.props.dispatch(fetchChangeIfNeeded(
      this.props.tenant, this.props.match.params.changeId, force))
      .then(() => {this.timer = setTimeout(this.updateData, 5000)})
    // Clear any running timer
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  componentDidMount () {
    document.title = this.props.match.params.changeId + ' | Zuul Status'
    super.componentDidMount()
  }

  componentWillUnmount () {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  render () {
    const { remoteData } = this.props
    const change = remoteData.change
    return (
      <React.Fragment>
        <div style={{float: 'right'}}>
          {this.renderSpinner()}
        </div><br />
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

export default connect(state => ({
  tenant: state.tenant,
  remoteData: state.change
}))(ChangeStatusPage)
