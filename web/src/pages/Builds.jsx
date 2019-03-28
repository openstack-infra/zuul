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

import { fetchBuilds } from '../api'
import TableFilters from '../containers/TableFilters'


class BuildsPage extends TableFilters {
  static propTypes = {
    tenant: PropTypes.object
  }

  constructor () {
    super()

    this.prepareTableHeaders()
    this.state = {
      builds: null,
      currentFilterType: this.filterTypes[0],
      activeFilters: [],
      currentValue: ''
    }
  }

  updateData = (filters) => {
    let queryString = ''
    if (filters) {
      filters.forEach(item => queryString += '&' + item.key + '=' + item.value)
    }
    this.setState({builds: null})
    fetchBuilds(this.props.tenant.apiPrefix, queryString).then(response => {
      this.setState({builds: response.data})
    })
  }

  componentDidMount () {
    document.title = 'Zuul Builds'
    if (this.props.tenant.name) {
      this.updateData(this.getFilterFromUrl())
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name) {
      this.updateData(this.getFilterFromUrl())
    }
  }

  prepareTableHeaders() {
    const headerFormat = value => <Table.Heading>{value}</Table.Heading>
    const cellFormat = (value) => (
      <Table.Cell>{value}</Table.Cell>)
    const linkBuildFormat = (value, rowdata) => (
      <Table.Cell>
        <Link to={this.props.tenant.linkPrefix + '/build/' + rowdata.rowData.uuid}>{value}</Link>
      </Table.Cell>
    )
    const linkChangeFormat = (value, rowdata) => (
      <Table.Cell>
        <a href={rowdata.rowData.ref_url}>{value ? rowdata.rowData.change+','+rowdata.rowData.patchset : rowdata.rowData.newrev ? rowdata.rowData.newrev.substr(0, 7) : rowdata.rowData.branch}</a>
      </Table.Cell>
    )
    this.columns = []
    this.filterTypes = []
    const myColumns = [
      'job',
      'project',
      'branch',
      'pipeline',
      'change',
      'duration',
      'start time',
      'result']
    myColumns.forEach(column => {
      let prop = column
      let formatter = cellFormat
      // Adapt column name and property name
      if (column === 'job') {
        prop = 'job_name'
      } else if (column === 'start time') {
        prop = 'start_time'
      } else if (column === 'change') {
        prop = 'change'
        formatter = linkChangeFormat
      } else if (column === 'result') {
        formatter = linkBuildFormat
      }
      const label = column.charAt(0).toUpperCase() + column.slice(1)
      this.columns.push({
        header: {label: label, formatters: [headerFormat]},
        property: prop,
        cell: {formatters: [formatter]}
      })
      if (prop !== 'start_time' && prop !== 'ref_url' && prop !== 'duration'
          && prop !== 'log_url' && prop !== 'uuid') {
        this.filterTypes.push({
          id: prop,
          title: label,
          placeholder: 'Filter by ' + label,
          filterType: 'text',
        })
      }
    })
    // Add build filter at the end
    this.filterTypes.push({
      id: 'uuid',
      title: 'Build',
      placeholder: 'Filter by Build UUID',
      filterType: 'text',
    })
  }

  renderTable (builds) {
    return (
      <Table.PfProvider
        striped
        bordered
        columns={this.columns}
      >
        <Table.Header/>
        <Table.Body
          rows={builds}
          rowKey='uuid'
          onRow={(row) => {
            switch (row.result) {
              case 'SUCCESS':
                return { className: 'success' }
              default:
                return { className: 'warning' }
            }
          }} />
      </Table.PfProvider>)
  }

  render() {
    const { builds } = this.state
    return (
      <React.Fragment>
        {this.renderFilter()}
        {builds ? this.renderTable(builds) : <p>Loading...</p>}
      </React.Fragment>
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(BuildsPage)
