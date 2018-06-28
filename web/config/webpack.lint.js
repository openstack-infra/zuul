const path = require('path');
const webpack = require('webpack');
const Merge = require('webpack-merge');
const CommonConfig = require('./webpack.common.js');
const BundleAnalyzer = require('webpack-bundle-analyzer');

module.exports = Merge(CommonConfig, {
  mode: 'development',
  module: {
    rules: [
      {
        enforce: 'pre',
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'tslint-loader',
            options: {
              emitErrors: true,
              typeCheck: false,

            }
          }
        ]
      },
      {
        enforce: 'pre',
        test: /\.js$/,
        use: [
          'babel-loader',
          'eslint-loader'
        ],
        exclude: /node_modules/,
      }
    ]
  },
  plugins: [
    new webpack.HotModuleReplacementPlugin(),
    new BundleAnalyzer.BundleAnalyzerPlugin({
      analyzerMode: 'static',
      reportFilename: '../../../reports/bundle.html',
      generateStatsFile: true,
      openAnalyzer: false,
      statsFilename: '../../../reports/stats.json',
    }),
  ]
})
