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
import { connect } from 'react-redux'
import PropTypes from 'prop-types'
import { Link } from 'react-router-dom'
import { Panel } from 'react-bootstrap'

import { fetchBuildIfNeeded } from '../actions/build'
import Refreshable from '../containers/Refreshable'


class BuildPage extends Refreshable {
  static propTypes = {
    match: PropTypes.object.isRequired,
    remoteData: PropTypes.object,
    tenant: PropTypes.object
  }

  updateData = (force) => {
    this.props.dispatch(fetchBuildIfNeeded(
      this.props.tenant, this.props.match.params.buildId, force))
  }

  componentDidMount () {
    document.title = 'Zuul Build'
    super.componentDidMount()
  }

  render () {
    const { remoteData } = this.props
    const build = remoteData.builds[this.props.match.params.buildId]
    if (!build) {
      return (<p>Loading...</p>)
    }
    const rows = []
    const myColumns = [
      'job_name', 'result', 'voting',
      'pipeline', 'start_time', 'end_time', 'duration',
      'project', 'branch', 'change', 'patchset', 'oldrev', 'newrev',
      'ref', 'new_rev', 'ref_url', 'log_url']

    myColumns.forEach(column => {
      let label = column
      let value = build[column]
      if (column === 'job_name') {
        label = 'job'
        value = (
          <Link to={this.props.tenant.linkPrefix + '/job/' + value}>
            {value}
          </Link>
        )
      }
      if (column === 'voting') {
        if (value) {
          value = 'true'
        } else {
          value = 'false'
        }
      }
      if (value && (column === 'log_url' || column === 'ref_url')) {
        value = <a href={value}>{value}</a>
      }
      if (column === 'log_url') {
        label = 'log url'
      }
      if (column === 'ref_url') {
        label = 'ref url'
      }
      if (value) {
        rows.push({key: label, value: value})
      }
    })
    return (
      <React.Fragment>
        <div style={{float: 'right'}}>
          {this.renderSpinner()}
        </div>
        <Panel>
          <Panel.Heading>Build result {build.uuid}</Panel.Heading>
          <Panel.Body>
            <table className="table table-striped table-bordered">
              <tbody>
                {rows.map(item => (
                  <tr key={item.key}>
                    <td>{item.key}</td>
                    <td>{item.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel.Body>
        </Panel>
      </React.Fragment>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
  remoteData: state.build,
}))(BuildPage)
