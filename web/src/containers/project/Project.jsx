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

import ProjectVariant from './ProjectVariant'


class Project extends React.Component {
  static propTypes = {
    project: PropTypes.object.isRequired,
  }

  state = {
    variantIdx: 0,
  }

  renderVariantTitle (variant, selected) {
    let title = variant.default_branch
    if (selected) {
      title = <strong>{title}</strong>
    }
    return title
  }

  render () {
    const { project } = this.props
    const { variantIdx } = this.state

    return (
      <React.Fragment>
        <h2>{project.canonical_name}</h2>
        <TabContainer id="zuul-project">
          <div>
            <Nav bsClass="nav nav-tabs nav-tabs-pf">
              {project.configs.map((variant, idx) => (
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
                <ProjectVariant variant={project.configs[variantIdx]} />
              </TabPane>
            </TabContent>
          </div>
        </TabContainer>
      </React.Fragment>
    )
  }
}

export default Project
