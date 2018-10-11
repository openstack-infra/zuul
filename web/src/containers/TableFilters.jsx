/* global URLSearchParams */
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

// Boiler plate code to manage table filtering

import * as React from 'react'
import PropTypes from 'prop-types'
import { Button, Filter, FormControl, Toolbar } from 'patternfly-react'


class TableFilters extends React.Component {
  static propTypes = {
    location: PropTypes.object
  }

  getFilterFromUrl = () => {
    const urlParams = new URLSearchParams(this.props.location.search)
    let activeFilters = []
    this.filterTypes.forEach(item => {
      urlParams.getAll(item.id).forEach(param => {
        activeFilters.push({
          label: item.title + ': ' + param,
          key: item.id,
          value: param})
      })
    })
    this.setState({activeFilters: activeFilters})
    return activeFilters
  }

  updateUrl (activeFilters) {
    let path = window.location.pathname
    if (activeFilters.length > 0) {
      path += '?'
      activeFilters.forEach((item, idx) => {
        if (idx > 0) {
          path += '&'
        }
        path += (
          encodeURIComponent(item.key)
          + '=' +
          encodeURIComponent(item.value)
        )
      })
    }
    window.history.pushState({path: path}, '', path)
  }

  filterAdded = (field, value) => {
    let filterText = ''
    if (field.title) {
      filterText = field.title
    } else {
      filterText = field
    }
    filterText += ': '

    if (value.filterCategory) {
      filterText +=
        (value.filterCategory.title || value.filterCategory) +
        '-' +
        (value.filterValue.title || value.filterValue)
    } else if (value.title) {
      filterText += value.title
    } else {
      filterText += value
    }

    let activeFilters = [...this.state.activeFilters, {
      label: filterText,
      key: field.id,
      value: value
    }]
    this.setState({ activeFilters: activeFilters })
    this.updateData(activeFilters)
    this.updateUrl(activeFilters)
  }

  selectFilterType = filterType => {
    const { currentFilterType } = this.state
    if (currentFilterType !== filterType) {
      this.setState(prevState => {
        return {
          currentValue: '',
          currentFilterType: filterType,
          filterCategory:
            filterType.filterType === 'complex-select'
              ? undefined
              : prevState.filterCategory,
          categoryValue:
            filterType.filterType === 'complex-select'
              ? ''
              : prevState.categoryValue
        }
      })
    }
  }

  filterValueSelected = filterValue => {
    const { currentFilterType, currentValue } = this.state

    if (filterValue !== currentValue) {
      this.setState({ currentValue: filterValue })
      if (filterValue) {
        this.filterAdded(currentFilterType, filterValue)
      }
    }
  }

  filterCategorySelected = category => {
    const { filterCategory } = this.state
    if (filterCategory !== category) {
      this.setState({ filterCategory: category, currentValue: '' })
    }
  }

  categoryValueSelected = value => {
    const { currentValue, currentFilterType, filterCategory } = this.state

    if (filterCategory && currentValue !== value) {
      this.setState({ currentValue: value })
      if (value) {
        let filterValue = {
          filterCategory: filterCategory,
          filterValue: value
        }
        this.filterAdded(currentFilterType, filterValue)
      }
    }
  }

  updateCurrentValue = event => {
    this.setState({ currentValue: event.target.value })
  }

  onValueKeyPress = keyEvent => {
    const { currentValue, currentFilterType } = this.state

    if (keyEvent.key === 'Enter' && currentValue && currentValue.length > 0) {
      this.setState({ currentValue: '' })
      this.filterAdded(currentFilterType, currentValue)
      keyEvent.stopPropagation()
      keyEvent.preventDefault()
    }
  }

  removeFilter = filter => {
    const { activeFilters } = this.state

    let index = activeFilters.indexOf(filter)
    if (index > -1) {
      let updated = [
        ...activeFilters.slice(0, index),
        ...activeFilters.slice(index + 1)
      ]
      this.setState({ activeFilters: updated })
      this.updateData(updated)
      this.updateUrl(updated)
    }
  }

  clearFilters = () => {
    this.setState({ activeFilters: [] })
    this.updateData()
    this.updateUrl([])
  }

  renderFilterInput() {
    const { currentFilterType, currentValue } = this.state
    if (!currentFilterType) {
      return null
    }
    return (
      <FormControl
        type={currentFilterType.filterType}
        value={currentValue}
        placeholder={currentFilterType.placeholder}
        onChange={e => this.updateCurrentValue(e)}
        onKeyPress={e => this.onValueKeyPress(e)}
        />
    )
  }

  renderFilter = () => {
    const { currentFilterType, activeFilters } = this.state
    return (
      <React.Fragment>
        <div style={{ width: 300 }}>
          <Filter>
            <Filter.TypeSelector
              filterTypes={this.filterTypes}
              currentFilterType={currentFilterType}
              onFilterTypeSelected={this.selectFilterType}
              />
            {this.renderFilterInput()}
          </Filter>
        </div>
        {activeFilters && activeFilters.length > 0 && (
          <Toolbar.Results>
            <Filter.ActiveLabel>{'Active Filters:'}</Filter.ActiveLabel>
            <Filter.List>
              {activeFilters.map((item, index) => {
                return (
                  <Filter.Item
                    key={index}
                    onRemove={this.removeFilter}
                    filterData={item}
                    >
                    {item.label}
                  </Filter.Item>
                )
              })}
          </Filter.List>
            <Button onClick={e => {
              e.preventDefault()
              this.clearFilters()
            }}>Clear All Filters</Button>
            </Toolbar.Results>
        )}
      </React.Fragment>
    )
  }
}

export default TableFilters
