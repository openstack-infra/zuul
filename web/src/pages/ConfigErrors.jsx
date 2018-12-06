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
  Icon
} from 'patternfly-react'

import { fetchConfigErrorsAction } from '../actions/configErrors'

class ConfigErrorsPage extends React.Component {
  static propTypes = {
    configErrors: PropTypes.object,
    tenant: PropTypes.object,
    dispatch: PropTypes.func
  }

  updateData = () => {
    this.props.dispatch(fetchConfigErrorsAction(this.props.tenant))
  }

  render () {
    const { configErrors } = this.props
    return (
      <React.Fragment>
        <div className="pull-right">
          <a className="refresh" onClick={() => {this.updateData()}}>
            <Icon type="fa" name="refresh" /> refresh&nbsp;&nbsp;
          </a>
        </div>
        <div className="pull-left">
          <ul className="list-group">
            {configErrors.map((item, idx) => {
              let ctxPath = item.source_context.path
              if (item.source_context.branch !== 'master') {
                ctxPath += ' (' + item.source_context.branch + ')'
              }
              return (
                <li className="list-group-item" key={idx}>
                  <h3>{item.source_context.project} - {ctxPath}</h3>
                  <p style={{whiteSpace: 'pre'}}>
                    {item.error}
                  </p>
                </li>
              )
            })}
          </ul>
        </div>
      </React.Fragment>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
  configErrors: state.configErrors
}))(ConfigErrorsPage)
