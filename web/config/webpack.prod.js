const path = require('path');
const webpack = require('webpack');
const Merge = require('webpack-merge');
const CommonConfig = require('./webpack.common.js');
const ArchivePlugin = require('webpack-archive-plugin');

module.exports = Merge(CommonConfig, {
  output: {
    filename: '[name].[chunkhash].js',
    // path.resolve(__dirname winds up relative to the config dir
    path: path.resolve(__dirname, '../../zuul/web/static'),
    publicPath: ''
  },
  plugins: [
    new webpack.LoaderOptionsPlugin({
      minimize: true,
      debug: false
    }),
    new webpack.DefinePlugin({
      'process.env': {
        'NODE_ENV': JSON.stringify('production')
      }
    }),
    // Keeps the vendor bundle from changing needlessly.
    new webpack.HashedModuleIdsPlugin(),
    new webpack.optimize.UglifyJsPlugin({
      warningsFilter: function(filename) {
        return ! /node_modules/.test(filename);
      },
      beautify: false,
      mangle: {
        screw_ie8: true,
        keep_fnames: true
      },
      compress: {
        screw_ie8: true
      },
      sourceMap: true,
      comments: false
    }),
    new ArchivePlugin({
      output: path.resolve(__dirname, '../../zuul-web'),
      format: [
        'tar',
      ],
      ext: 'tgz'
    })
  ]
})
