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


class ChangePanel extends React.Component {
  static propTypes = {
    globalExpanded: PropTypes.bool.isRequired,
    change: PropTypes.object.isRequired,
    tenant: PropTypes.object
  }

  constructor () {
    super()
    this.state = {
      expanded: false
    }
    this.onClick = this.onClick.bind(this)
    this.clicked = false
  }

  onClick () {
    let expanded = this.state.expanded
    if (!this.clicked) {
      expanded = this.props.globalExpanded
    }
    this.clicked = true
    this.setState({ expanded: !expanded })
  }

  time (ms, words) {
    if (typeof (words) === 'undefined') {
      words = false
    }
    let seconds = (+ms) / 1000
    let minutes = Math.floor(seconds / 60)
    let hours = Math.floor(minutes / 60)
    seconds = Math.floor(seconds % 60)
    minutes = Math.floor(minutes % 60)
    let r = ''
    if (words) {
      if (hours) {
        r += hours
        r += ' hr '
      }
      r += minutes + ' min'
    } else {
      if (hours < 10) {
        r += '0'
      }
      r += hours + ':'
      if (minutes < 10) {
        r += '0'
      }
      r += minutes + ':'
      if (seconds < 10) {
        r += '0'
      }
      r += seconds
    }
    return r
  }

  enqueueTime (ms) {
    // Special format case for enqueue time to add style
    let hours = 60 * 60 * 1000
    let now = Date.now()
    let delta = now - ms
    let status = 'text-success'
    let text = this.time(delta, true)
    if (delta > (4 * hours)) {
      status = 'text-danger'
    } else if (delta > (2 * hours)) {
      status = 'text-warning'
    }
    return <span className={status}>{text}</span>
  }

  renderChangeLink (change) {
    let changeId = change.id || 'NA'
    let changeTitle = changeId
    // Fall back to display the ref if there is no change id
    if (changeId === 'NA' && change.ref) {
      changeTitle = change.ref
    }
    let changeText = ''
    if (change.url !== null) {
      let githubId = changeId.match(/^([0-9]+),([0-9a-f]{40})$/)
      if (githubId) {
        changeTitle = githubId
        changeText = '#' + githubId[1]
      } else if (/^[0-9a-f]{40}$/.test(changeId)) {
        changeText = changeId.slice(0, 7)
      }
    } else if (changeId.length === 40) {
      changeText = changeId.slice(0, 7)
    }
    return (
      <small>
        <a href={change.url}>
          {changeText !== '' ? (
            <abbr title={changeTitle}>{changeText}</abbr>) : changeTitle}
        </a>
      </small>)
  }

  renderProgressBar (change) {
    let jobPercent = Math.floor(100 / change.jobs.length)
    return (
      <div className='progress zuul-change-total-result'>
        {change.jobs.map((job, idx) => {
          let result = job.result ? job.result.toLowerCase() : null
          if (result === null) {
            result = job.url ? 'in progress' : 'queued'
          }
          if (result !== 'queued') {
            let className = ''
            switch (result) {
              case 'success':
                className = ' progress-bar-success'
                break
              case 'lost':
              case 'failure':
                className = ' progress-bar-danger'
                break
              case 'unstable':
                className = ' progress-bar-warning'
                break
              case 'in progress':
              case 'queued':
                break
              default:
                break
            }
            return <div className={'progress-bar' + className}
              key={idx}
              title={job.name}
              style={{width: jobPercent + '%'}}/>
          } else {
            return ''
          }
        })}
      </div>
    )
  }

  renderTimer (change) {
    let remainingTime
    if (change.remaining_time === null) {
      remainingTime = 'unknown'
    } else {
      remainingTime = this.time(change.remaining_time, true)
    }
    return (
      <React.Fragment>
        <small title='Remaining Time' className='time'>
          {remainingTime}
        </small>
        <br />
        <small title='Elapsed Time' className='time'>
          {this.enqueueTime(change.enqueue_time)}
        </small>
      </React.Fragment>
    )
  }

  renderJobProgressBar (elapsedTime, remainingTime) {
    let progressPercent = 100 * (elapsedTime / (elapsedTime +
                                                remainingTime))
    // Show animation in preparation phase
    let className
    let progressWidth = progressPercent
    if (Number.isNaN(progressPercent)) {
      progressWidth = 100
      progressPercent = 0
      className = 'progress-bar-striped progress-bar-animated'
    }

    return (
      <div className='progress zuul-job-result'>
        <div className={'progress-bar ' + className}
          role='progressbar'
          aria-valuenow={progressPercent}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{'width': progressWidth + '%'}}
        />
      </div>
    )
  }

  renderJobStatusLabel (result) {
    let className
    switch (result) {
      case 'success':
        className = 'label-success'
        break
      case 'failure':
        className = 'label-danger'
        break
      case 'unstable':
        className = 'label-warning'
        break
      case 'skipped':
        className = 'label-info'
        break
      // 'in progress' 'queued' 'lost' 'aborted' ...
      default:
        className = 'label-default'
    }

    return (
      <span className={'zuul-job-result label ' + className}>{result}</span>
    )
  }

  renderJob (job) {
    const { tenant } = this.props
    let name = ''
    if (job.result !== null) {
      name = <a className='zuul-job-name' href={job.report_url}>{job.name}</a>
    } else if (job.url !== null) {
      let url = job.url
      // TODO: remove that first if block when
      // I074b3a88a893e04d504e9cf21ced14ba86efc7ec is merged
      if (job.url.match('stream.html')) {
        const buildUuid = job.url.split('?')[1].split('&')[0].split('=')[1]
        const to = (
          tenant.linkPrefix + '/stream/' + buildUuid + '?logfile=console.log'
        )
        name = <Link to={to}>{job.name}</Link>
      } else if (job.url.match('stream/')) {
        const to = (
          tenant.linkPrefix + '/' + job.url
        )
        name = <Link to={to}>{job.name}</Link>
      } else {
        name = <a className='zuul-job-name' href={url}>{job.name}</a>
      }
    } else {
      name = <span className='zuul-job-name'>{job.name}</span>
    }
    let resultBar
    let result = job.result ? job.result.toLowerCase() : null
    if (result === null) {
      if (job.url === null) {
        result = 'queued'
      } else if (job.paused !== null && job.paused) {
        result = 'paused'
      } else {
        result = 'in progress'
      }
    }
    if (result === 'in progress') {
      resultBar = this.renderJobProgressBar(
        job.elapsed_time, job.remaining_time)
    } else {
      resultBar = this.renderJobStatusLabel(result)
    }

    return (
      <span>
        {name}
        {resultBar}
        {job.voting === false ? (
          <small className='zuul-non-voting-desc'> (non-voting)</small>) : ''}
        <div style={{clear: 'both'}} />
      </span>)
  }

  renderJobList (jobs) {
    return (
      <ul className='list-group zuul-patchset-body'>
        {jobs.map((job, idx) => (
          <li key={idx} className='list-group-item zuul-change-job'>
            {this.renderJob(job)}
          </li>
        ))}
      </ul>)
  }

  render () {
    const { expanded } = this.state
    const { change, globalExpanded } = this.props
    let expand = globalExpanded
    if (this.clicked) {
      expand = expanded
    }
    const header = (
      <div className='panel panel-default zuul-change'>
        <div className='panel-heading zuul-patchset-header'
             onClick={this.onClick}>
          <div className='row'>
            <div className='col-xs-8'>
              <span className='change_project'>{change.project}</span>
              <div className='row'>
                <div className='col-xs-4'>
                  {this.renderChangeLink(change)}
                </div>
                <div className='col-xs-8'>
                  {this.renderProgressBar(change)}
                </div>
              </div>
            </div>
            {change.live === true ? (
              <div className='col-xs-4 text-right'>
                {this.renderTimer(change)}
              </div>
            ) : ''}
          </div>
        </div>
        {expand ? this.renderJobList(change.jobs) : ''}
      </div>
    )
    return (
      <React.Fragment>
        {header}
      </React.Fragment>
    )
  }
}

export default connect(state => ({tenant: state.tenant}))(ChangePanel)
