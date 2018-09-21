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
import { fetchProject } from '../api'


class ProjectPage extends React.Component {
  static propTypes = {
    match: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  state = {
    project: null
  }

  fixProjectConfig(project) {
    let templateIdx = []
    let idx
    project.configs.forEach((config, idx) => {
      if (config.default_branch === null) {
        // This must be a template
        templateIdx.push(idx)
        config.pipelines.forEach(templatePipeline => {
          let pipeline = project.configs[idx - 1].pipelines.filter(
            item => item.name === templatePipeline.name)
          if (pipeline.length === 0) {
            // Pipeline doesn't exist in project config
            project.configs[idx - 1].pipelines.push(templatePipeline)
          } else {
            if (pipeline[0].queue_name === null) {
              pipeline[0].queue_name = templatePipeline.queue_name
            }
            templatePipeline.jobs.forEach(job => {
              pipeline[0].jobs.push(job)
            })
          }
        })
      }
    })
    for (idx = templateIdx.length - 1; idx >= 0; idx -= 1) {
      project.configs.splice(templateIdx[idx], 1)
    }
  }

  updateData = () => {
    fetchProject(
      this.props.tenant.apiPrefix, this.props.match.params.projectName)
      .then(response => {
        // TODO: fix api to return template name or merge them
        // in the mean-time, merge the jobs in project configs
        this.fixProjectConfig(response.data)
        this.setState({project: response.data})
      })
  }

  componentDidMount () {
    document.title = 'Zuul Project | ' + this.props.match.params.projectName
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name ||
        this.props.match.params.projectName !==
        prevProps.match.params.projectName) {
      this.updateData()
    }
  }

  render () {
    const { project } = this.state
    if (!project) {
      return (<p>Loading...</p>)
    }
    return (
      <Project project={project} />
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(ProjectPage)
