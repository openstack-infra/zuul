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

// Boiler plate code to manage refresh button

import * as React from 'react'
import PropTypes from 'prop-types'
import {
  Icon,
  Spinner
} from 'patternfly-react'


class Refreshable extends React.Component {
  static propTypes = {
    tenant: PropTypes.object,
    remoteData: PropTypes.object,
  }

  componentDidMount () {
    if (this.props.tenant.name) {
      this.updateData()
    }
  }

  componentDidUpdate (prevProps) {
    if (this.props.tenant.name !== prevProps.tenant.name) {
      this.updateData()
    }
  }

  renderSpinner () {
    const { remoteData } = this.props
    return (
      <Spinner loading={ remoteData.isFetching }>
        <a className="refresh" onClick={() => {this.updateData(true)}}>
          <Icon type="fa" name="refresh" /> refresh&nbsp;&nbsp;
        </a>
      </Spinner>
    )
  }
}

export default Refreshable
