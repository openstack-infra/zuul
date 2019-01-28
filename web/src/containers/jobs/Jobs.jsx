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
import { TreeView } from 'patternfly-react'


class JobsList extends React.Component {
  static propTypes = {
    tenant: PropTypes.object,
    jobs: PropTypes.array,
  }

  render () {
    const { jobs } = this.props

    const linkPrefix = this.props.tenant.linkPrefix + '/job/'

    // job index map
    const jobMap = {}
    // nodes contains the tree data
    const nodes = []
    // visited contains individual node
    const visited = {}
    // getNode returns the tree node and visit each parents
    const getNode = function (job) {
      if (!visited[job.name]) {
        // Collect parents
        let parents = []
        if (job.variants) {
          for (let jobVariant of job.variants) {
            if (jobVariant.parent &&
                parents.indexOf(jobVariant.parent) === -1) {
              parents.push(jobVariant.parent)
            }
          }
        }
        visited[job.name] = {
          text: (
            <React.Fragment>
              <Link to={linkPrefix + job.name}>{job.name}</Link>
              {job.description && (
                <span style={{marginLeft: '10px'}}>{job.description}</span>
              )}
            </React.Fragment>),
          icon: 'fa fa-cube',
          state: {
            expanded: true,
          },
          parents: parents,
        }
        // Visit parent recursively
        for (let parent of parents) {
          getNode(jobMap[parent])
        }
      }
      return visited[job.name]
    }
    // index job list
    for (let job of jobs) {
      jobMap[job.name] = job
    }
    // process job list
    for (let job of jobs) {
      const jobNode = getNode(job)
      let attached = false
      // add tree node to each parent and expand the parent
      for (let parent of jobNode.parents) {
        const parentNode = visited[parent]
        if (!parentNode) {
          console.log('Job ', job.name, ' parent ', parent, ' does not exist!')
          continue
        }
        if (!parentNode.nodes) {
          parentNode.nodes = []
        }
        parentNode.nodes.push(jobNode)
        attached = true
      }
      // else add node at the tree root
      if (!attached || jobNode.parents.length === 0) {
        nodes.push(jobNode)
      }
    }
    return (
      <div className='tree-view-container'>
        <TreeView nodes={nodes} />
      </div>
    )
  }
}

export default connect(state => ({
  tenant: state.tenant,
}))(JobsList)
