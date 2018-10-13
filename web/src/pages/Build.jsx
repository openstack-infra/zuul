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

import { fetchBuild } from '../api'


class BuildPage extends React.Component {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  state = {
    build: null
  }

  updateData = () => {
    fetchBuild(this.props.tenant.apiPrefix, this.props.match.params.buildId)
      .then(response => {
        this.setState({build: response.data})
      })
  }

  componentDidMount () {
    document.title = 'Zuul Build'
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name) {
      this.updateData()
    }
  }

  render () {
    const { build } = this.state
    if (!build) {
      return (<p>Loading...</p>)
    }
    const rows = []
    const myColumns = [
      'job_name', 'result', 'voting',
      'pipeline', 'start_time', 'end_time', 'duration',
      'project', 'branch', 'ref', 'new_rev', 'ref_url',
      'log_url']

    myColumns.forEach(column => {
      let label = column
      let value = build[column]
      if (column === 'job_name') {
        label = 'Job'
        value = (
          <Link to={this.props.tenant.linkPrefix + '/job/' + value}>
            {value}
          </Link>
        )
      }
      if (column === 'voting') {
        if (value) {
          value = 'Yes'
        } else {
          value = 'No'
        }
      }
      if (value && (column === 'log_url' || column === 'ref_url')) {
        value = <a href={value}>{value}</a>
      }
      if (value) {
        rows.push({key: label, value: value})
      }
    })
    return (
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
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(BuildPage)
