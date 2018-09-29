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
import { Link } from 'react-router-dom'
import { Table } from 'patternfly-react'

import { fetchTenants } from '../api'

class TenantsPage extends React.Component {
  constructor () {
    super()

    this.state = {
      tenants: []
    }
  }

  componentDidMount () {
    document.title = 'Zuul Tenants'
    fetchTenants().then(response => {
      this.setState({tenants: response.data})
    })
  }

  render () {
    const { tenants } = this.state
    if (tenants.length === 0) {
      return (<p>Loading...</p>)
    }
    const headerFormat = value => <Table.Heading>{value}</Table.Heading>
    const cellFormat = (value) => (
      <Table.Cell>{value}</Table.Cell>)
    const columns = []
    const myColumns = ['name', 'status', 'jobs', 'builds', 'projects', 'queue']
    myColumns.forEach(column => {
      columns.push({
        header: {label: column,
          formatters: [headerFormat]},
        property: column,
        cell: {formatters: [cellFormat]}
      })
    })
    tenants.forEach(tenant => {
      tenant.status = (
        <Link to={'/t/' + tenant.name + '/status'}>Status</Link>)
      tenant.jobs = (
        <Link to={'/t/' + tenant.name + '/jobs'}>Jobs</Link>)
      tenant.builds = (
        <Link to={'/t/' + tenant.name + '/builds'}>Builds</Link>)
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
          rows={tenants}
          rowKey="name"
        />
      </Table.PfProvider>)
  }
}

export default TenantsPage
