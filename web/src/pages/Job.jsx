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

import Job from '../containers/job/Job'
import { fetchJob } from '../api'


class JobPage extends React.Component {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  state = {
    job: null
  }

  updateData = () => {
    fetchJob(this.props.tenant.apiPrefix, this.props.match.params.jobName)
      .then(response => {
        this.setState({job: response.data})
      })
  }

  componentDidMount () {
    document.title = 'Zuul Job | ' + this.props.match.params.jobName
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name ||
       this.props.match.params.jobName !== prevProps.match.params.jobName) {
      this.updateData()
    }
  }

  render () {
    const { job } = this.state
    if (!job) {
      return (<p>Loading...</p>)
    }
    return (
      <Job job={job} />
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(JobPage)
