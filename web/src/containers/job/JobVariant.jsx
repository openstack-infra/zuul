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
import { ReactHeight } from 'react-height'
import ReactJson from 'react-json-view'
import {
  Icon,
} from 'patternfly-react'

import SourceContext from '../SourceContext'
import Nodeset from './Nodeset'
import Role from './Role'
import JobProject from './JobProject'


class JobVariant extends React.Component {
  static propTypes = {
    descriptionMaxHeight: PropTypes.number.isRequired,
    parent: PropTypes.object,
    tenant: PropTypes.object,
    variant: PropTypes.object.isRequired
  }

  renderStatus (variant) {
    const status = [{
      icon: variant.voting ? 'connected' : 'disconnected',
      name: variant.voting ? 'Voting' : 'Non-voting'
    }]
    if (variant.abstract) {
      status.push({
        icon: 'infrastructure',
        name: 'Abstract'
      })
    }
    if (variant.final) {
      status.push({
        icon: 'infrastructure',
        name: 'Final'
      })
    }
    if (variant.post_review) {
      status.push({
        icon: 'locked',
        name: 'Post review'
      })
    }
    if (variant.protected) {
      status.push({
        icon: 'locked',
        name: 'Protected'
      })
    }

    return (
      <div className="list-view-pf-additional-info">
          {status.map((item, idx) => (
            <div key={idx} className="list-view-pf-additional-info-item">
              <Icon type='pf' name={item.icon} />
              {item.name}
            </div>
          ))}
      </div>
    )
  }

  render () {
    const { tenant, variant, descriptionMaxHeight } = this.props
    const rows = []

    const jobInfos = [
      'description', 'context', 'status',
      'parent', 'attempts', 'timeout', 'semaphore', 'implied_branch',
      'nodeset', 'variables',
    ]
    jobInfos.forEach(key => {
      let label = key
      let value = variant[key]

      if (label === 'context') {
        value = (
          <SourceContext
            context={variant.source_context}
            showBranch={true}/>
        )
      }
      if (label === 'status') {
        value = this.renderStatus(variant)
      }

      if (!value) {
        return
      }

      if (label === 'nodeset') {
        value = <Nodeset nodeset={value} />
      }

      if (label === 'parent') {
        value = (
          <Link to={tenant.linkPrefix + '/job/' + value}>
            {value}
          </Link>
        )
      }
      if (label === 'variables') {
        value = (
          <span style={{whiteSpace: 'pre'}}>
            <ReactJson
              src={value}
              sortKeys={true}
              enableClipboard={false}
              displayDataTypes={false}/>
          </span>
        )
      }
      if (label === 'description') {
        const style = {
          whiteSpace: 'pre'
        }
        if (descriptionMaxHeight > 0) {
          style.minHeight = descriptionMaxHeight
        }
        value = (
          <ReactHeight onHeightReady={height => {
              if (height > descriptionMaxHeight) {
                this.props.parent.setState({descriptionMaxHeight: height})
              }
            }}>
            <div style={style}>
              {value}
            </div>
          </ReactHeight>
        )
      }
      rows.push({label: label, value: value})
    })
    const jobInfosList = [
      'required_projects', 'dependencies', 'files', 'irrelevant_files', 'roles'
    ]
    jobInfosList.forEach(key => {
      let label = key
      let values = variant[key]

      if (values.length === 0) {
        return
      }
      const items = (
        <ul className='list-group'>
          {values.map((value, idx) => {
            let item
            if (label === 'required_projects') {
              item = <JobProject project={value} />
            } else if (label === 'roles') {
              item = <Role role={value} />
            } else {
              item = value
            }
            return (
              <li className='list-group-item' key={idx}>
                {item}
              </li>
            )
          })}
        </ul>
      )
      rows.push({label: label, value: items})
    })
    return (
      <div>
        <table className='table table-striped table-bordered'>
          <tbody>
            {rows.map(item => (
              <tr key={item.label}>
                <td style={{width: '10%'}}>{item.label}</td>
                <td>{item.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(JobVariant)
