const path = require('path');
const webpack = require('webpack');
const Merge = require('webpack-merge');
const CommonConfig = require('./webpack.common.js');
const CleanWebpackPlugin = require('clean-webpack-plugin');
const ArchivePlugin = require('webpack-archive-plugin');

module.exports = Merge(CommonConfig, {
  mode: 'production',
  output: {
    filename: '[name].[chunkhash].js',
    // path.resolve(__dirname winds up relative to the config dir
    path: path.resolve(__dirname, '../../zuul/web/static'),
    publicPath: ''
  },
  optimization: {
    minimize: true
  },
  plugins: [
    new CleanWebpackPlugin(
        ['zuul/web/static'], { root: path.resolve(__dirname, '../..')}),
    // Keeps the vendor bundle from changing needlessly.
    new webpack.HashedModuleIdsPlugin(),
    new ArchivePlugin({
      output: path.resolve(__dirname, '../../zuul-web'),
      format: [
        'tar',
      ],
      ext: 'tgz'
    })
  ]
})
