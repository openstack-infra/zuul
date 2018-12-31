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
import { Link } from 'react-router-dom'
import { Table } from 'patternfly-react'

import { fetchProjectsIfNeeded } from '../actions/projects'
import Refreshable from '../containers/Refreshable'


class ProjectsPage extends Refreshable {
  static propTypes = {
    tenant: PropTypes.object,
    remoteData: PropTypes.object,
    dispatch: PropTypes.func
  }

  updateData (force) {
    this.props.dispatch(fetchProjectsIfNeeded(this.props.tenant, force))
  }

  componentDidMount () {
    document.title = 'Zuul Projects'
    super.componentDidMount()
  }

  render () {
    const { remoteData } = this.props
    const projects = remoteData.projects[this.props.tenant.name]

    if (!projects) {
      return (<p>Loading...</p>)
    }

    const headerFormat = value => <Table.Heading>{value}</Table.Heading>
    const cellFormat = (value) => (
      <Table.Cell>{value}</Table.Cell>)
    const cellProjectFormat = (value) => (
      <Table.Cell>
        <Link to={this.props.tenant.linkPrefix + '/project/' + value}>
          {value}
        </Link>
      </Table.Cell>)
    const cellBuildFormat = (value) => (
      <Table.Cell>
        <Link to={this.props.tenant.linkPrefix + '/builds?project=' + value}>
          builds
        </Link>
      </Table.Cell>)
    const columns = []
    const myColumns = ['name', 'connection', 'type', 'last builds']
    myColumns.forEach(column => {
      let formatter = cellFormat
      let prop = column
      if (column === 'name') {
        formatter = cellProjectFormat
      }
      if (column === 'connection') {
        prop = 'connection_name'
      }
      if (column === 'last builds') {
        prop = 'name'
        formatter = cellBuildFormat
      }
      columns.push({
        header: {label: column,
          formatters: [headerFormat]},
        property: prop,
        cell: {formatters: [formatter]}
      })
    })
    return (
      <React.Fragment>
        <div style={{float: 'right'}}>
          {this.renderSpinner()}
        </div>
        <Table.PfProvider
          striped
          bordered
          hover
          columns={columns}
        >
          <Table.Header/>
          <Table.Body
            rows={projects}
            rowKey="name"
          />
        </Table.PfProvider>
      </React.Fragment>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
  remoteData: state.projects,
}))(ProjectsPage)
