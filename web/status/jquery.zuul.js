/* global Image, jQuery */
// jquery plugin for Zuul status page
//
// Copyright 2012 OpenStack Foundation
// Copyright 2013 Timo Tijhof
// Copyright 2013 Wikimedia Foundation
// Copyright 2014 Rackspace Australia
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

import RedImage from '../images/red.png'
import GreyImage from '../images/grey.png'
import GreenImage from '../images/green.png'
import BlackImage from '../images/black.png'
import LineImage from '../images/line.png'
import LineAngleImage from '../images/line-angle.png'
import LineTImage from '../images/line-t.png';

(function ($) {
  function setCookie (name, value) {
    document.cookie = name + '=' + value + '; path=/'
  }

  function readCookie (name, defaultValue) {
    let nameEQ = name + '='
    let ca = document.cookie.split(';')
    for (let i = 0; i < ca.length; i++) {
      let c = ca[i]
      while (c.charAt(0) === ' ') {
        c = c.substring(1, c.length)
      }
      if (c.indexOf(nameEQ) === 0) {
        return c.substring(nameEQ.length, c.length)
      }
    }
    return defaultValue
  }

  $.zuul = function (options) {
    options = $.extend({
      'enabled': true,
      'graphite_url': '',
      'source': 'status',
      'source_data': null,
      'msg_id': '#zuul_msg',
      'pipelines_id': '#zuul_pipelines',
      'queue_events_num': '#zuul_queue_events_num',
      'queue_management_events_num': '#zuul_queue_management_events_num',
      'queue_results_num': '#zuul_queue_results_num'
    }, options)

    let collapsedExceptions = []
    let currentFilter = readCookie('zuul_filter_string', '')
    let changeSetInURL = window.location.href.split('#')[1]
    if (changeSetInURL) {
      currentFilter = changeSetInURL
    }
    let $jq

    let xhr
    let zuulGraphUpdateCount = 0
    let zuulSparklineURLs = {}

    function getSparklineURL (pipelineName) {
      if (options.graphite_url !== '') {
        if (!(pipelineName in zuulSparklineURLs)) {
          zuulSparklineURLs[pipelineName] = $.fn.graphite
            .geturl({
              url: options.graphite_url,
              from: '-8hours',
              width: 100,
              height: 26,
              margin: 0,
              hideLegend: true,
              hideAxes: true,
              hideGrid: true,
              target: [
                'color(stats.gauges.zuul.pipeline.' + pipelineName +
                ".current_changes, '6b8182')"
              ]
            })
        }
        return zuulSparklineURLs[pipelineName]
      }
      return false
    }

    let format = {
      job: function (job) {
        let $jobLine = $('<span />')

        if (job.result !== null) {
          $jobLine.append(
            $('<a />')
              .addClass('zuul-job-name')
              .attr('href', job.report_url)
              .text(job.name)
          )
        } else if (job.url !== null) {
          $jobLine.append(
            $('<a />')
              .addClass('zuul-job-name')
              .attr('href', job.url)
              .text(job.name)
          )
        } else {
          $jobLine.append(
            $('<span />')
              .addClass('zuul-job-name')
              .text(job.name)
          )
        }

        $jobLine.append(this.job_status(job))

        if (job.voting === false) {
          $jobLine.append(
            $(' <small />')
              .addClass('zuul-non-voting-desc')
              .text(' (non-voting)')
          )
        }

        $jobLine.append($('<div style="clear: both"></div>'))
        return $jobLine
      },

      job_status: function (job) {
        let result = job.result ? job.result.toLowerCase() : null
        if (result === null) {
          result = job.url ? 'in progress' : 'queued'
        }

        if (result === 'in progress') {
          return this.job_progress_bar(job.elapsed_time,
            job.remaining_time)
        } else {
          return this.status_label(result)
        }
      },

      status_label: function (result) {
        let $status = $('<span />')
        $status.addClass('zuul-job-result label')

        switch (result) {
          case 'success':
            $status.addClass('label-success')
            break
          case 'failure':
            $status.addClass('label-danger')
            break
          case 'unstable':
            $status.addClass('label-warning')
            break
          case 'skipped':
            $status.addClass('label-info')
            break
          // 'in progress' 'queued' 'lost' 'aborted' ...
          default:
            $status.addClass('label-default')
        }
        $status.text(result)
        return $status
      },

      job_progress_bar: function (elapsedTime, remainingTime) {
        let progressPercent = 100 * (elapsedTime / (elapsedTime +
                                                              remainingTime))
        let $barInner = $('<div />')
          .addClass('progress-bar')
          .attr('role', 'progressbar')
          .attr('aria-valuenow', 'progressbar')
          .attr('aria-valuemin', progressPercent)
          .attr('aria-valuemin', '0')
          .attr('aria-valuemax', '100')
          .css('width', progressPercent + '%')

        let $barOutter = $('<div />')
          .addClass('progress zuul-job-result')
          .append($barInner)

        return $barOutter
      },

      enqueueTime: function (ms) {
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
        return '<span class="' + status + '">' + text + '</span>'
      },

      time: function (ms, words) {
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
      },

      changeTotalProgressBar: function (change) {
        let jobPercent = Math.floor(100 / change.jobs.length)
        let $barOutter = $('<div />')
          .addClass('progress zuul-change-total-result')

        $.each(change.jobs, function (i, job) {
          let result = job.result ? job.result.toLowerCase() : null
          if (result === null) {
            result = job.url ? 'in progress' : 'queued'
          }

          if (result !== 'queued') {
            let $barInner = $('<div />')
              .addClass('progress-bar')

            switch (result) {
              case 'success':
                $barInner.addClass('progress-bar-success')
                break
              case 'lost':
              case 'failure':
                $barInner.addClass('progress-bar-danger')
                break
              case 'unstable':
                $barInner.addClass('progress-bar-warning')
                break
              case 'in progress':
              case 'queued':
                break
            }
            $barInner.attr('title', job.name)
              .css('width', jobPercent + '%')
            $barOutter.append($barInner)
          }
        })
        return $barOutter
      },

      changeHeader: function (change) {
        let changeId = change.id || 'NA'

        let $changeLink = $('<small />')
        if (change.url !== null) {
          let githubId = changeId.match(/^([0-9]+),([0-9a-f]{40})$/)
          if (githubId) {
            $changeLink.append(
              $('<a />').attr('href', change.url).append(
                $('<abbr />')
                  .attr('title', changeId)
                  .text('#' + githubId[1])
              )
            )
          } else if (/^[0-9a-f]{40}$/.test(changeId)) {
            let changeIdShort = changeId.slice(0, 7)
            $changeLink.append(
              $('<a />').attr('href', change.url).append(
                $('<abbr />')
                  .attr('title', changeId)
                  .text(changeIdShort)
              )
            )
          } else {
            $changeLink.append(
              $('<a />').attr('href', change.url).text(changeId)
            )
          }
        } else {
          if (changeId.length === 40) {
            changeId = changeId.substr(0, 7)
          }
          $changeLink.text(changeId)
        }

        let $changeProgressRowLeft = $('<div />')
          .addClass('col-xs-4')
          .append($changeLink)
        let $changeProgressRowRight = $('<div />')
          .addClass('col-xs-8')
          .append(this.changeTotalProgressBar(change))

        let $changeProgressRow = $('<div />')
          .addClass('row')
          .append($changeProgressRowLeft)
          .append($changeProgressRowRight)

        let $projectSpan = $('<span />')
          .addClass('change_project')
          .text(change.project)

        let $left = $('<div />')
          .addClass('col-xs-8')
          .append($projectSpan, $changeProgressRow)

        let remainingTime = this.time(change.remaining_time, true)
        let enqueueTime = this.enqueueTime(change.enqueue_time)
        let $remainingTime = $('<small />').addClass('time')
          .attr('title', 'Remaining Time').html(remainingTime)
        let $enqueueTime = $('<small />').addClass('time')
          .attr('title', 'Elapsed Time').html(enqueueTime)

        let $right = $('<div />')
        if (change.live === true) {
          $right.addClass('col-xs-4 text-right')
            .append($remainingTime, $('<br />'), $enqueueTime)
        }

        let $header = $('<div />')
          .addClass('row')
          .append($left, $right)
        return $header
      },

      change_list: function (jobs) {
        let format = this
        let $list = $('<ul />')
          .addClass('list-group zuul-patchset-body')

        $.each(jobs, function (i, job) {
          let $item = $('<li />')
            .addClass('list-group-item')
            .addClass('zuul-change-job')
            .append(format.job(job))
          $list.append($item)
        })

        return $list
      },

      changePanel: function (change) {
        let $header = $('<div />')
          .addClass('panel-heading zuul-patchset-header')
          .append(this.changeHeader(change))

        let panelId = change.id ? change.id.replace(',', '_')
          : change.project.replace('/', '_') +
                                           '-' + change.enqueue_time
        let $panel = $('<div />')
          .attr('id', panelId)
          .addClass('panel panel-default zuul-change')
          .append($header)
          .append(this.change_list(change.jobs))

        $header.click(this.toggle_patchset)
        return $panel
      },

      change_status_icon: function (change) {
        let iconFile = GreenImage
        let iconTitle = 'Succeeding'

        if (change.active !== true) {
          // Grey icon
          iconFile = GreyImage
          iconTitle = 'Waiting until closer to head of queue to' +
                        ' start jobs'
        } else if (change.live !== true) {
          // Grey icon
          iconFile = GreyImage
          iconTitle = 'Dependent change required for testing'
        } else if (change.failing_reasons &&
                         change.failing_reasons.length > 0) {
          let reason = change.failing_reasons.join(', ')
          iconTitle = 'Failing because ' + reason
          if (reason.match(/merge conflict/)) {
            // Black icon
            iconFile = BlackImage
          } else {
            // Red icon
            iconFile = RedImage
          }
        }

        let $icon = $('<img />')
          .attr('src', iconFile)
          .attr('title', iconTitle)
          .css('display', 'block')

        return $icon
      },

      change_with_status_tree: function (change, changeQueue) {
        let $changeRow = $('<tr />')

        for (let i = 0; i < changeQueue._tree_columns; i++) {
          let $treeCell = $('<td />')
            .css('height', '100%')
            .css('padding', '0 0 10px 0')
            .css('margin', '0')
            .css('width', '16px')
            .css('min-width', '16px')
            .css('overflow', 'hidden')
            .css('vertical-align', 'top')

          if (i < change._tree.length && change._tree[i] !== null) {
            $treeCell.css('background-image',
              'url(' + LineImage + ')')
              .css('background-repeat', 'repeat-y')
          }

          if (i === change._tree_index) {
            $treeCell.append(
              this.change_status_icon(change))
          }
          if (change._tree_branches.indexOf(i) !== -1) {
            let $image = $('<img />')
              .css('vertical-align', 'baseline')
            if (change._tree_branches.indexOf(i) ===
                            change._tree_branches.length - 1) {
              // Angle line
              $image.attr('src', LineAngleImage)
            } else {
              // T line
              $image.attr('src', LineTImage)
            }
            $treeCell.append($image)
          }
          $changeRow.append($treeCell)
        }

        let changeWidth = 360 - 16 * changeQueue._tree_columns
        let $changeColumn = $('<td />')
          .css('width', changeWidth + 'px')
          .addClass('zuul-change-cell')
          .append(this.changePanel(change))

        $changeRow.append($changeColumn)

        let $changeTable = $('<table />')
          .addClass('zuul-change-box')
          .css('-moz-box-sizing', 'content-box')
          .css('box-sizing', 'content-box')
          .append($changeRow)

        return $changeTable
      },

      pipeline_sparkline: function (pipelineName) {
        if (options.graphite_url !== '') {
          let $sparkline = $('<img />')
            .addClass('pull-right')
            .attr('src', getSparklineURL(pipelineName))
          return $sparkline
        }
        return false
      },

      pipeline_header: function (pipeline, count) {
        // Format the pipeline name, sparkline and description
        let $headerDiv = $('<div />')
          .addClass('zuul-pipeline-header')

        let $heading = $('<h3 />')
          .css('vertical-align', 'middle')
          .text(pipeline.name)
          .append(
            $('<span />')
              .addClass('badge pull-right')
              .css('vertical-align', 'middle')
              .css('margin-top', '0.5em')
              .text(count)
          )
          .append(this.pipeline_sparkline(pipeline.name))

        $headerDiv.append($heading)

        if (typeof pipeline.description === 'string') {
          let descr = $('<small />')
          $.each(pipeline.description.split(/\r?\n\r?\n/),
            function (index, descrPart) {
              descr.append($('<p />').text(descrPart))
            })
          $headerDiv.append($('<p />').append(descr))
        }
        return $headerDiv
      },

      pipeline: function (pipeline, count) {
        let format = this
        let $html = $('<div />')
          .addClass('zuul-pipeline col-md-4')
          .append(this.pipeline_header(pipeline, count))

        $.each(pipeline.change_queues, function (queueIndex, changeQueue) {
          $.each(changeQueue.heads, function (headIndex, changes) {
            if (pipeline.change_queues.length > 1 && headIndex === 0) {
              let name = changeQueue.name
              let shortName = name
              if (shortName.length > 32) {
                shortName = shortName.substr(0, 32) + '...'
              }
              $html.append($('<p />')
                .text('Queue: ')
                .append(
                  $('<abbr />')
                    .attr('title', name)
                    .text(shortName)
                )
              )
            }

            $.each(changes, function (changeIndex, change) {
              let $changeBox =
                        format.change_with_status_tree(
                          change, changeQueue)
              $html.append($changeBox)
              format.display_patchset($changeBox)
            })
          })
        })
        return $html
      },

      toggle_patchset: function (e) {
        // Toggle showing/hiding the patchset when the header is clicked.
        if (e.target.nodeName.toLowerCase() === 'a') {
          // Ignore clicks from gerrit patch set link
          return
        }

        // Grab the patchset panel
        let $panel = $(e.target).parents('.zuul-change')
        let $body = $panel.children('.zuul-patchset-body')
        $body.toggle(200)
        let collapsedIndex = collapsedExceptions.indexOf(
          $panel.attr('id'))
        if (collapsedIndex === -1) {
          // Currently not an exception, add it to list
          collapsedExceptions.push($panel.attr('id'))
        } else {
          // Currently an except, remove from exceptions
          collapsedExceptions.splice(collapsedIndex, 1)
        }
      },

      display_patchset: function ($changeBox, animate) {
        // Determine if to show or hide the patchset and/or the results
        // when loaded

        // See if we should hide the body/results
        let $panel = $changeBox.find('.zuul-change')
        let panelChange = $panel.attr('id')
        let $body = $panel.children('.zuul-patchset-body')
        let expandByDefault = $('#expand_by_default')
          .prop('checked')

        let collapsedIndex = collapsedExceptions
          .indexOf(panelChange)

        if ((expandByDefault && collapsedIndex === -1) ||
                    (!expandByDefault && collapsedIndex !== -1)) {
          // Expand by default, or is an exception
          $body.show(animate)
        } else {
          $body.hide(animate)
        }

        // Check if we should hide the whole panel
        let panelProject = $panel.find('.change_project').text()
          .toLowerCase()

        let panelPipeline = $changeBox
          .parents('.zuul-pipeline')
          .find('.zuul-pipeline-header > h3')
          .html()
          .toLowerCase()

        if (currentFilter !== '') {
          let showPanel = false
          let filter = currentFilter.trim().split(/[\s,]+/)
          $.each(filter, function (index, filterVal) {
            if (filterVal !== '') {
              filterVal = filterVal.toLowerCase()
              if (panelProject.indexOf(filterVal) !== -1 ||
                      panelPipeline.indexOf(filterVal) !== -1 ||
                      panelChange.indexOf(filterVal) !== -1) {
                showPanel = true
              }
            }
          })
          if (showPanel === true) {
            $changeBox.show(animate)
          } else {
            $changeBox.hide(animate)
          }
        } else {
          $changeBox.show(animate)
        }
      }
    }

    let app = {
      schedule: function (app) {
        app = app || this
        if (!options.enabled) {
          setTimeout(function () { app.schedule(app) }, 5000)
          return
        }
        app.update().always(function () {
          setTimeout(function () { app.schedule(app) }, 5000)
        })

        // Only update graphs every minute
        if (zuulGraphUpdateCount > 11) {
          zuulGraphUpdateCount = 0
          $.zuul.update_sparklines()
        }
      },
      injest: function (data, $msg) {
        if ('message' in data) {
          $msg.removeClass('alert-danger')
            .addClass('alert-info')
            .text(data.message)
            .show()
        } else {
          $msg.empty()
            .hide()
        }

        if ('zuul_version' in data) {
          $('#zuul-version-span').text(data.zuul_version)
        }
        if ('last_reconfigured' in data) {
          let lastReconfigured =
                        new Date(data.last_reconfigured)
          $('#last-reconfigured-span').text(
            lastReconfigured.toString())
        }

        let $pipelines = $(options.pipelines_id)
        $pipelines.html('')
        $.each(data.pipelines, function (i, pipeline) {
          let count = app.create_tree(pipeline)
          $pipelines.append(
            format.pipeline(pipeline, count))
        })

        $(options.queue_events_num).text(
          data.trigger_event_queue
            ? data.trigger_event_queue.length : '0'
        )
        $(options.queue_results_num).text(
          data.result_event_queue
            ? data.result_event_queue.length : '0'
        )
      },
      /** @return {jQuery.Promise} */
      update: function () {
        // Cancel the previous update if it hasn't completed yet.
        if (xhr) {
          xhr.abort()
        }

        this.emit('update-start')
        let app = this

        let $msg = $(options.msg_id)
        if (options.source_data !== null) {
          app.injest(options.source_data, $msg)
          return
        }
        xhr = $.getJSON(options.source)
          .done(function (data) {
            app.injest(data, $msg)
          })
          .fail(function (jqXHR, statusText, errMsg) {
            if (statusText === 'abort') {
              return
            }
            $msg.text(options.source + ': ' + errMsg)
              .addClass('alert-danger')
              .removeClass('zuul-msg-wrap-off')
              .show()
          })
          .always(function () {
            xhr = undefined
            app.emit('update-end')
          })

        return xhr
      },

      update_sparklines: function () {
        $.each(zuulSparklineURLs, function (name, url) {
          let newimg = new Image()
          let parts = url.split('#')
          newimg.src = parts[0] + '#' + new Date().getTime()
          $(newimg).load(function () {
            zuulSparklineURLs[name] = newimg.src
          })
        })
      },

      emit: function () {
        $jq.trigger.apply($jq, arguments)
        return this
      },
      on: function () {
        $jq.on.apply($jq, arguments)
        return this
      },
      one: function () {
        $jq.one.apply($jq, arguments)
        return this
      },

      controlForm: function () {
        // Build the filter form filling anything from cookies

        let $controlForm = $('<form />')
          .attr('role', 'form')
          .addClass('form-inline')
          .submit(this.handleFilterChange)

        $controlForm
          .append(this.filterFormGroup())
          .append(this.expandFormGroup())

        return $controlForm
      },

      filterFormGroup: function () {
        // Update the filter form with a clear button if required

        let $label = $('<label />')
          .addClass('control-label')
          .attr('for', 'filter_string')
          .text('Filters')
          .css('padding-right', '0.5em')

        let $input = $('<input />')
          .attr('type', 'text')
          .attr('id', 'filter_string')
          .addClass('form-control')
          .attr('title',
            'project(s), pipeline(s) or review(s) comma ' +
                          'separated')
          .attr('value', currentFilter)

        $input.change(this.handleFilterChange)

        let $clearIcon = $('<span />')
          .addClass('form-control-feedback')
          .addClass('glyphicon glyphicon-remove-circle')
          .attr('id', 'filter_form_clear_box')
          .attr('title', 'clear filter')
          .css('cursor', 'pointer')

        $clearIcon.click(function () {
          $('#filter_string').val('').change()
        })

        if (currentFilter === '') {
          $clearIcon.hide()
        }

        let $formGroup = $('<div />')
          .addClass('form-group has-feedback')
          .append($label, $input, $clearIcon)
        return $formGroup
      },

      expandFormGroup: function () {
        let expandByDefault = (
          readCookie('zuul_expand_by_default', false) === 'true')

        let $checkbox = $('<input />')
          .attr('type', 'checkbox')
          .attr('id', 'expand_by_default')
          .prop('checked', expandByDefault)
          .change(this.handleExpandByDefault)

        let $label = $('<label />')
          .css('padding-left', '1em')
          .html('Expand by default: ')
          .append($checkbox)

        let $formGroup = $('<div />')
          .addClass('checkbox')
          .append($label)
        return $formGroup
      },

      handleFilterChange: function () {
        // Update the filter and save it to a cookie
        currentFilter = $('#filter_string').val()
        setCookie('zuul_filter_string', currentFilter)
        if (currentFilter === '') {
          $('#filter_form_clear_box').hide()
        } else {
          $('#filter_form_clear_box').show()
        }

        $('.zuul-change-box').each(function (index, obj) {
          let $changeBox = $(obj)
          format.display_patchset($changeBox, 200)
        })
        return false
      },

      handleExpandByDefault: function (e) {
        // Handle toggling expand by default
        setCookie('zuul_expand_by_default', e.target.checked)
        collapsedExceptions = []
        $('.zuul-change-box').each(function (index, obj) {
          let $changeBox = $(obj)
          format.display_patchset($changeBox, 200)
        })
      },

      create_tree: function (pipeline) {
        let count = 0
        let pipelineMaxTreeColumns = 1
        $.each(pipeline.change_queues,
          function (changeQueueIndex, changeQueue) {
            let tree = []
            let maxTreeColumns = 1
            let changes = []
            let lastTreeLength = 0
            $.each(changeQueue.heads, function (headIndex, head) {
              $.each(head, function (changeIndex, change) {
                changes[change.id] = change
                change._tree_position = changeIndex
              })
            })
            $.each(changeQueue.heads, function (headIndex, head) {
              $.each(head, function (changeIndex, change) {
                if (change.live === true) {
                  count += 1
                }
                let idx = tree.indexOf(change.id)
                if (idx > -1) {
                  change._tree_index = idx
                  // remove...
                  tree[idx] = null
                  while (tree[tree.length - 1] === null) {
                    tree.pop()
                  }
                } else {
                  change._tree_index = 0
                }
                change._tree_branches = []
                change._tree = []
                if (typeof (change.items_behind) === 'undefined') {
                  change.items_behind = []
                }
                change.items_behind.sort(function (a, b) {
                  return (changes[b]._tree_position - changes[a]._tree_position)
                })
                $.each(change.items_behind, function (i, id) {
                  tree.push(id)
                  if (tree.length > lastTreeLength && lastTreeLength > 0) {
                    change._tree_branches.push(tree.length - 1)
                  }
                })
                if (tree.length > maxTreeColumns) {
                  maxTreeColumns = tree.length
                }
                if (tree.length > pipelineMaxTreeColumns) {
                  pipelineMaxTreeColumns = tree.length
                }
                change._tree = tree.slice(0) // make a copy
                lastTreeLength = tree.length
              })
            })
            changeQueue._tree_columns = maxTreeColumns
          })
        pipeline._tree_columns = pipelineMaxTreeColumns
        return count
      }
    }

    $jq = $(app)
    return {
      options: options,
      format: format,
      app: app,
      jq: $jq
    }
  }
}(jQuery))
