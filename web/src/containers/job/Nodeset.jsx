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
  AggregateStatusCount,
  AggregateStatusNotifications,
  AggregateStatusNotification,
  Card,
  CardBody,
  CardTitle,
  Icon,
} from 'patternfly-react'


class Nodeset extends React.Component {
  static propTypes = {
    nodeset: PropTypes.object.isRequired
  }

  render () {
    const { nodeset } = this.props
    const nodes = (
      <ul className="list-group">
        {nodeset.nodes.map((item, idx) => {
          const groups = []
          nodeset.groups.forEach(group => {
            if (group.nodes.indexOf(item.name) !== -1) {
              groups.push(group.name)
            }
          })
          return (
            <li className="list-group-item" key={idx}>
              <span title="Node name">
                {item.name}
              </span> -&nbsp;
              <span title="Label name">
                {item.label}
              </span>
              <span title="Groups">
                {groups.length > 0 && ' (' + groups.map(item => (item)) + ') '}
              </span>
            </li>)
          })}
      </ul>
    )
    return (
      <Card accented aggregated>
        <CardTitle>
          {nodeset.name}
        </CardTitle>
        <CardBody>
          <AggregateStatusNotifications>
            <AggregateStatusNotification>
              <span title="Nodes">
                <Icon type="pf" name="server" />
                <AggregateStatusCount>
                  {nodeset.nodes.length}
                </AggregateStatusCount>
              </span>
            </AggregateStatusNotification>
            <AggregateStatusNotification>
              <span title="Groups">
                <Icon type="pf" name="server-group" />
                <AggregateStatusCount>
                  {nodeset.groups.length}
                </AggregateStatusCount>
              </span>
            </AggregateStatusNotification>
          </AggregateStatusNotifications>
          {nodes}
        </CardBody>
      </Card>
    )
  }
}

export default Nodeset
