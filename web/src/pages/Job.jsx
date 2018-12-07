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
import Refreshable from '../containers/Refreshable'
import { fetchJobIfNeeded } from '../actions/job'


class JobPage extends Refreshable {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object,
    remoteData: PropTypes.object,
    dispatch: PropTypes.func
  }

  updateData = (force) => {
    this.props.dispatch(fetchJobIfNeeded(
      this.props.tenant, this.props.match.params.jobName, force))
  }

  componentDidMount () {
    document.title = 'Zuul Job | ' + this.props.match.params.jobName
    super.componentDidMount()
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name ||
       this.props.match.params.jobName !== prevProps.match.params.jobName) {
      this.updateData()
    }
  }

  render () {
    const { remoteData } = this.props
    const tenantJobs = remoteData.jobs[this.props.tenant.name]
    const jobName = this.props.match.params.jobName
    return (
      <React.Fragment>
        <div style={{float: 'right'}}>
          {this.renderSpinner()}
        </div>
        {tenantJobs && tenantJobs[jobName] && <Job job={tenantJobs[jobName]} />}
      </React.Fragment>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
  remoteData: state.job,
}))(JobPage)
