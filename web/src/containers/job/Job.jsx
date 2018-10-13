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
import {
  Nav,
  NavItem,
  TabContainer,
  TabPane,
  TabContent,
} from 'patternfly-react'

import JobVariant from './JobVariant'

class Job extends React.Component {
  static propTypes = {
    job: PropTypes.array.isRequired,
  }

  state = {
    variantIdx: 0,
    descriptionMaxHeight: 0
  }

  resetMaxHeight = () => {
    this.setState({descriptionMaxHeight: 0})
  }

  componentDidUpdate (prevProps, prevState) {
    if (prevState.descriptionMaxHeight > 0) {
      this.resetMaxHeight()
    }
  }

  renderVariantTitle (variant, selected) {
    let title = variant.variant_description
    if (!title) {
      title = ''
      variant.branches.forEach((item) => {
        if (title) {
          title += ', '
        }
        title += item
      })
    }
    if (selected) {
      title = <strong>{title}</strong>
    }
    return title
  }

  render () {
    const { job } = this.props
    const { variantIdx, descriptionMaxHeight } = this.state

    return (
      <React.Fragment>
        <h2>{job[0].name}</h2>
        <TabContainer id="zuul-job">
          <div>
            <Nav bsClass="nav nav-tabs nav-tabs-pf">
              {job.map((variant, idx) => (
                <NavItem
                  key={idx}
                  onClick={() => this.setState({variantIdx: idx})}>
                  <div>
                    {this.renderVariantTitle(variant, variantIdx === idx)}
                  </div>
                </NavItem>
              ))}
            </Nav>
            <TabContent>
              <TabPane>
                <JobVariant
                  variant={job[variantIdx]}
                  descriptionMaxHeight={descriptionMaxHeight}
                  parent={this}
                  />
              </TabPane>
            </TabContent>
          </div>
        </TabContainer>
      </React.Fragment>
    )
  }
}

export default Job
