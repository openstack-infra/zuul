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

import Change from './Change'


class ChangeQueue extends React.Component {
  static propTypes = {
    pipeline: PropTypes.string.isRequired,
    queue: PropTypes.object.isRequired,
    expanded: PropTypes.bool.isRequired
  }

  render () {
    const { queue, pipeline, expanded } = this.props
    let shortName = queue.name
    if (shortName.length > 32) {
      shortName = shortName.substr(0, 32) + '...'
    }
    let changesList = []
    queue.heads.forEach((changes, changeIdx) => {
      changes.forEach((change, idx) => {
        changesList.push(
          <Change
            change={change}
            queue={queue}
            expanded={expanded}
            key={changeIdx.toString() + idx}
            />)
      })
    })
    return (
      <div className="change-queue" data-zuul-pipeline={pipeline}>
        <p>Queue: <abbr title={queue.name}>{shortName}</abbr></p>
        {changesList}
      </div>)
  }
}

export default ChangeQueue
