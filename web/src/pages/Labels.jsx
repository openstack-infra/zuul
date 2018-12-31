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
import { Table } from 'patternfly-react'

import { fetchLabels } from '../api'


class LabelsPage extends React.Component {
  static propTypes = {
    tenant: PropTypes.object
  }

  state = {
    labels: null
  }

  updateData () {
    fetchLabels(this.props.tenant.apiPrefix).then(response => {
      this.setState({labels: response.data})
    })
  }

  componentDidMount () {
    document.title = 'Zuul Labels'
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
    const { labels } = this.state
    if (!labels) {
      return (<p>Loading...</p>)
    }

    const headerFormat = value => <Table.Heading>{value}</Table.Heading>
    const cellFormat = value => <Table.Cell>{value}</Table.Cell>
    const columns = []
    const myColumns = ['name']
    myColumns.forEach(column => {
      let formatter = cellFormat
      let prop = column
      columns.push({
        header: {label: column, formatters: [headerFormat]},
        property: prop,
        cell: {formatters: [formatter]}
      })
    })
    return (
      <Table.PfProvider
        striped
        bordered
        hover
        columns={columns}
      >
        <Table.Header/>
        <Table.Body
          rows={labels}
          rowKey="name"
        />
      </Table.PfProvider>)
  }
}

export default connect(state => ({tenant: state.tenant}))(LabelsPage)
