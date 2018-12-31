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

import LineAngleImage from '../../images/line-angle.png'
import LineTImage from '../../images/line-t.png'
import ChangePanel from './ChangePanel'


class Change extends React.Component {
  static propTypes = {
    change: PropTypes.object.isRequired,
    queue: PropTypes.object.isRequired,
    expanded: PropTypes.bool.isRequired,
    tenant: PropTypes.object
  }

  renderStatusIcon (change) {
    let iconGlyph = 'pficon pficon-ok'
    let iconTitle = 'Succeeding'
    if (change.active !== true) {
      iconGlyph = 'pficon pficon-pending'
      iconTitle = 'Waiting until closer to head of queue to' +
        ' start jobs'
    } else if (change.live !== true) {
      iconGlyph =  'pficon pficon-info'
      iconTitle = 'Dependent change required for testing'
    } else if (change.failing_reasons &&
               change.failing_reasons.length > 0) {
      let reason = change.failing_reasons.join(', ')
      iconTitle = 'Failing because ' + reason
      if (reason.match(/merge conflict/)) {
        iconGlyph = 'pficon pficon-error-circle-o zuul-build-merge-conflict'
      } else {
        iconGlyph = 'pficon pficon-error-circle-o'
      }
    }
    const icon = (
        <span
          className={'zuul-build-status ' + iconGlyph}
          title={iconTitle} />
    )
    if (change.live) {
      return (
        <Link to={this.props.tenant.linkPrefix + '/status/change/' + change.id}>
          {icon}
        </Link>
      )
    } else {
      return icon
    }
  }

  renderLineImg (change, i) {
    let image = LineTImage
    if (change._tree_branches.indexOf(i) === change._tree_branches.length - 1) {
      // Angle line
      image = LineAngleImage
    }
    return <img alt="Line" src={image} style={{verticalAlign: 'baseline'}} />
  }

  render () {
    const { change, queue, expanded } = this.props
    let row = []
    let i
    for (i = 0; i < queue._tree_columns; i++) {
      let className = ''
      if (i < change._tree.length && change._tree[i] !== null) {
        className = ' zuul-change-row-line'
      }
      row.push(
        <td key={i} className={'zuul-change-row' + className}>
          {i === change._tree_index ? this.renderStatusIcon(change) : ''}
          {change._tree_branches.indexOf(i) !== -1 ? (
            this.renderLineImg(change, i)) : ''}
        </td>)
    }
    let changeWidth = 360 - 16 * queue._tree_columns
    row.push(
      <td key={i + 1}
        className="zuul-change-cell"
        style={{width: changeWidth + 'px'}}>
        <ChangePanel change={change} globalExpanded={expanded} />
      </td>
    )
    return (
      <table className="zuul-change-box" style={{boxSizing: 'content-box'}}>
        <tbody>
          <tr>{row}</tr>
        </tbody>
      </table>
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(Change)
