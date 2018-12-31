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

import Project from '../containers/project/Project'
import { fetchProjectIfNeeded } from '../actions/project'
import Refreshable from '../containers/Refreshable'


class ProjectPage extends Refreshable {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object,
    remoteData: PropTypes.object,
    dispatch: PropTypes.func
  }

  updateData = (force) => {
    this.props.dispatch(fetchProjectIfNeeded(
      this.props.tenant, this.props.match.params.projectName, force))
  }

  componentDidMount () {
    document.title = 'Zuul Project | ' + this.props.match.params.projectName
    super.componentDidMount()
  }

  render () {
    const { remoteData } = this.props
    const tenantProjects = remoteData.projects[this.props.tenant.name]
    const projectName = this.props.match.params.projectName
    return (
      <React.Fragment>
        <div style={{float: 'right'}}>
          {this.renderSpinner()}
        </div>
        {tenantProjects && tenantProjects[projectName] &&
         <Project project={tenantProjects[projectName]} />}
      </React.Fragment>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
  remoteData: state.project,
}))(ProjectPage)
