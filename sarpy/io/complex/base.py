# -*- coding: utf-8 -*-
"""
The base elements for reading and writing complex data files.
"""

import os
import logging
from typing import Union, Tuple
from datetime import datetime

import numpy

from .sicd_elements.SICD import SICDType
from .sicd_elements.ImageCreation import ImageCreationType
from ...__about__ import __title__, __version__
from .utils import validate_range, reverse_range, int_func, integer_types, string_types


__classification__ = "UNCLASSIFIED"
__author__ = "Thomas McCullough"


#################
# Chipper definitions - this is base functionality for the most basic reading

class BaseChipper(object):
    """
    Base class defining basic functionality for the literal extraction of data
    from a file. The intent of this class is to be a callable in the following form:
    :code:`data = BaseChipper(entry1, entry2)`, where each entry is a tuple or
    int of the form `[[[start], stop,] step]`.

    Similarly, we are able to use more traditional Python slicing syntax

    .. code-block::

        data = BaseChipper[slice1[, slice2]]

    **Extension Requirement:** This provides the basic implementation for the work
    flow, but it is **required** that any extension provide a concrete implementation
    for actually reading from the raw file in `read_raw_fun`.

    **Extension Consideration:** It is possible that the basic functionality for
    conversion of raw data to complex data requires something more nuanced than
    the default provided in the `_data_to_complex` method.
    """
    __slots__ = ('_data_size', '_complex_type', '_symmetry')

    def __init__(self, data_size, symmetry=(False, False, False), complex_type=False):
        """

        Parameters
        ----------
        data_size : tuple
            The full size of the data *after* any required transformation. See
            `data_size` property.
        symmetry : tuple
            Describes any required data transformation. See the `symmetry` property.
        complex_type : callable|bool
            For complex type handling.
            If callable, then this is expected to transform the raw data to the complex data.
            If this evaluates to `True`, then the assumption is that real/imaginary
            components are stored in adjacent bands, which will be combined into a
            single band upon extraction.
        """

        if not (isinstance(complex_type, bool) or callable(complex_type)):
            raise ValueError('complex-type must be a boolean or a callable')
        self._complex_type = complex_type

        if not isinstance(symmetry, tuple):
            symmetry = tuple(symmetry)
        if len(symmetry) != 3:
            raise ValueError(
                'The symmetry parameter must have length 3, and got {}.'.format(symmetry))
        self._symmetry = tuple([bool(entry) for entry in symmetry])

        if not isinstance(data_size, tuple):
            data_size = tuple(data_size)
        if len(data_size) != 2:
            raise ValueError(
                'The data_size parameter must have length 2, and got {}.'.format(data_size))
        data_size = (int_func(data_size[0]), int_func(data_size[1]))
        if data_size[0] < 0 or data_size[1] < 0:
            raise ValueError('All entries of data_size {} must be non-negative.'.format(data_size))
        if self._symmetry[2]:
            self._data_size = (data_size[1], data_size[0])
        else:
            self._data_size = data_size

    @property
    def symmetry(self):
        """
        Tuple[bool, bool, bool]: Entries of the form (`flip1`, `flip2`, `swap_axes`).
        This describes necessary symmetry transformation to be performed to convert
        from raw (file storage) order into the order expected (analysis order).

        * `flip1=True` - we reverse order in the first axis, wrt raw order.

        * `flip2=True` - we reverse order in the second axis, wrt raw order).

        * `swap_axes=True` - we switch the two axes, after any required flipping.
        """

        return self._symmetry

    @property
    def data_size(self):
        """
        Tuple[int, int]: Two element tuple of the form `(rows, columns)`, which provides the
        size of the data, after any necessary symmetry transformations have been applied.
        Note that this excludes the number of bands in the image.
        """

        return self._data_size

    def __call__(self, range1, range2):
        """
        Reads and fetches data. Note that :code:`chipper(range1, range2)` is an alias
        for :code:`chipper.read_chip(range1, range2)`.

        Parameters
        ----------
        range1 : None|int|tuple
        range2 : none|int|tuple

        Returns
        -------
        numpy.ndarray
        """

        data = self._read_raw_fun(range1, range2)
        data = self._data_to_complex(data)

        # make a one band image flat
        if data.ndim == 3 and data.shape[2] == 1:
            data = numpy.reshape(data, data.shape[:-1])

        data = self._reorder_data(data)
        return data

    def __getitem__(self, item):
        """
        Reads and returns data using more traditional to python slice functionality.
        After slice interpretation, this is analogous to :func:`__call__` or :func:`read_chip`.

        Parameters
        ----------
        item : None|int|slice|tuple

        Returns
        -------
        numpy.ndarray
        """

        range1, range2 = self._slice_to_args(item)
        return self.__call__(range1, range2)

    @staticmethod
    def _slice_to_args(item):
        # type: (Union[None, int, slice, tuple]) -> tuple
        def parse(entry):
            if isinstance(entry, integer_types):
                return entry, entry+1, 1
            if isinstance(entry, slice):
                return entry.start, entry.stop, entry.step

        # this input is assumed to come from slice parsing
        if isinstance(item, tuple) and len(item) > 2:
            raise ValueError(
                'Chipper received slice argument {}. We cannot slice on more than two dimensions.'.format(item))
        if isinstance(item, tuple):
            return parse(item[0]), parse(item[1])
        else:
            return parse(item), None

    def _reorder_arguments(self, range1, range2):
        """
        Reinterpret the range arguments into actual "physical" arguments of memory,
        in light of the symmetry attribute.

        Parameters
        ----------
        range1 : None|int|tuple
            * if `None`, then the range is not limited in first axis
            * if `int` = step size
            * if (`int`, `int`) = `end`, `step size`
            * if (`int`, `int`, `int`) = `start`, `stop`, `step size`
        range2 : None|int|tuple
            same as `range1`, except for the second axis.

        Returns
        -------
        None|int|tuple
            actual range 1 - in light of `range1`, `range2` and symmetry
        None|int|tuple
            actual range 2 - in light of `range1`, `range2` and symmetry
        """

        if isinstance(range1, (numpy.ndarray, list)):
            range1 = tuple(int_func(el) for el in range1)
        if isinstance(range2, (numpy.ndarray, list)):
            range2 = tuple(int_func(el) for el in range2)

        if not (range1 is None or isinstance(range1, integer_types) or isinstance(range1, tuple)):
            raise TypeError('range1 is of type {}, but must be an instance of None, '
                            'int or tuple.'.format(range1))
        if isinstance(range1, tuple) and len(range1) > 3:
            raise TypeError('range1 must have no more than 3 entries, received {}.'.format(range1))

        if not (range2 is None or isinstance(range2, integer_types) or isinstance(range2, tuple)):
            raise TypeError('range2 is of type {}, but must be an instance of None, '
                            'int or tuple.'.format(range2))
        if isinstance(range2, tuple) and len(range2) > 3:
            raise TypeError('range2 must have no more than 3 entries, received {}.'.format(range2))

        # switch the axes symmetry dictates
        if self._symmetry[2]:
            range1, range2 = range2, range1
            lim1, lim2 = self._data_size[1], self._data_size[0]
        else:
            lim1, lim2 = self._data_size[0], self._data_size[1]

        # validate the first range
        if self._symmetry[0]:
            real_arg1 = reverse_range(range1, lim1)
        else:
            real_arg1 = validate_range(range1, lim1)
        # validate the second range
        if self._symmetry[1]:
            real_arg2 = reverse_range(range2, lim2)
        else:
            real_arg2 = validate_range(range2, lim2)

        return real_arg1, real_arg2

    def _data_to_complex(self, data):
        # type: (numpy.ndarray) -> numpy.ndarray
        if callable(self._complex_type):
            return self._complex_type(data)  # is this actually necessary?
        elif self._complex_type:
            if data.dtype.name in ('complex64', 'complex128'):
                return data
            out = numpy.zeros((data.shape[0], data.shape[1], int_func(data.shape[2]/2)), dtype=numpy.complex64)
            out.real = data[:, :, 0::2]
            out.imag = data[:, :, 1::2]
            return out
        else:
            # nothing to be done
            return data

    def _reorder_data(self, data):
        # type: (numpy.ndarray) -> numpy.ndarray
        if self._symmetry[2]:
            data = numpy.swapaxes(data, 1, 0)
        return data

    def _read_raw_fun(self, range1, range2):
        """
        Reads data as stored in a file, before any complex data and symmetry
        transformations are applied. The one potential exception to the "raw"
        file orientation of the data is that bands will always be returned in the
        first dimension (data[n,:,:] is the nth band -- "band sequential" or BSQ,
        as stored in Python's memory), regardless of how the data is stored in
        the file.

        Parameters
        ----------
        range1 : None|int|tuple
            * if `None`, then the range is not limited in first axis
            * if `int` = step size
            * if (`int`, `int`) = `end`, `step size`
            * if (`int`, `int`, `int`) = `start`, `stop`, `step size`
        range2 : None|int|tuple
            same as `range1`, except for the second axis.

        Returns
        -------
        numpy.ndarray
            the (mostly) raw data read from the file
        """

        # Should generally begin as:
        # arange1, arange2 = self._reorder_arguments(range1, range2)

        raise NotImplementedError


class SubsetChipper(BaseChipper):
    """
    Permits transparent extraction from a particular subset of the possible data range
    """

    __slots__ = ('_data_size', '_complex_type', '_symmetry', 'shift1', 'shift2', 'parent_chipper')

    def __init__(self, parent_chipper, dim1bounds, dim2bounds):
        """

        Parameters
        ----------
        parent_chipper : BaseChipper
        dim1bounds : numpy.ndarray|list|tuple
        dim2bounds: numpy.ndarray|list|tuple
        """

        if not isinstance(parent_chipper, BaseChipper):
            raise TypeError('parent_chipper is required to be an instance of BaseChipper, '
                            'got type {}'.format(type(parent_chipper)))

        data_size = (dim1bounds[1] - dim1bounds[0], dim2bounds[1] - dim2bounds[0])
        self.shift1 = dim1bounds[0]
        self.shift2 = dim2bounds[0]
        self.parent_chipper = parent_chipper
        super(SubsetChipper, self).__init__(data_size, symmetry=(False, False, False), complex_type=False)

    def _reformat_bounds(self, range1, range2):
        def _get_start(entry, shift, bound):
            if entry is None:
                return shift
            entry = int_func(entry)
            if -bound < entry < 0:
                return shift + bound + entry
            elif 0 <= entry < bound:
                return shift + entry
            raise ValueError(
                'Got slice start entry {}, which must be in the range '
                '({}, {})'.format(entry, -bound, bound))

        def _get_end(entry, shift, bound):
            if entry is None:
                return shift
            entry = int_func(entry)
            if -bound <= entry < 0:
                return shift + bound + entry
            elif 0 <= entry <= bound:
                return shift + entry
            raise ValueError(
                'Got slice end entry {}, which must be in the range '
                '[{}, {}]'.format(entry, -bound, bound))

        def _get_range(rng, shift, bound):
            return (
                _get_start(rng[0], shift, bound),
                _get_end(rng[1], shift, bound),
                rng[2])
        arange1 = _get_range(range1, self.shift1, self._data_size[0])
        arange2 = _get_range(range2, self.shift2, self._data_size[1])
        return arange1, arange2

    def _read_raw_fun(self, range1, range2):
        arange1, arange2 = self._reformat_bounds(range1, range2)
        return self.parent_chipper.__call__(arange1, arange2)


#################
# Base Reader definition

class BaseReader(object):
    """
    Abstract file reader class
    """

    __slots__ = ('_sicd_meta', '_chipper', '_data_size')

    def __init__(self, sicd_meta, chipper):
        """

        Parameters
        ----------
        sicd_meta : None|SICDType|Tuple[SICDType]
            `None`, the SICD metadata object, or tuple of objects
        chipper : BaseChipper|Tuple[BaseChipper]
            a chipper object, or tuple of chipper objects
        """

        if isinstance(sicd_meta, list):
            sicd_meta = tuple(sicd_meta)
        if isinstance(chipper, list):
            chipper = tuple(chipper)

        # validate sicd_meta input
        if sicd_meta is None:
            pass
        elif isinstance(sicd_meta, tuple):
            for el in sicd_meta:
                if not isinstance(el, SICDType):
                    raise TypeError(
                        'Got a collection for sicd_meta, and all elements are required '
                        'to be instances of SICDType.')
        elif not isinstance(sicd_meta, SICDType):
            raise TypeError('sicd_meta argument is required to be a SICDType, or collection of SICDType objects')
        self._sicd_meta = sicd_meta

        # validate chipper input
        if isinstance(chipper, tuple):
            for el in chipper:
                if not isinstance(el, BaseChipper):
                    raise TypeError(
                        'Got a collection for chipper, and all elements are required '
                        'to be instances of BaseChipper.')
        elif not isinstance(chipper, BaseChipper):
            raise TypeError(
                'chipper argument is required to be a BaseChipper instance, or collection of BaseChipper objects')
        self._chipper = chipper

        # determine data_size
        if isinstance(chipper, BaseChipper):
            data_size = chipper.data_size
        else:
            data_size = tuple(el.data_size for el in chipper)
        self._data_size = data_size

    @property
    def sicd_meta(self):
        """
        None|SICDType|Tuple[SICDType]: the sicd meta_data or meta_data collection.
        """

        return self._sicd_meta

    @property
    def data_size(self):
        """
        Tuple[int, int]|Tuple[Tuple[int, int], ...]: the data size(s) of the form (rows, cols).
        """

        return self._data_size

    def get_sicds_as_tuple(self):
        """
        Get the sicd or sicd collection as a tuple - for simplicity and consistency of use.

        Returns
        -------
        Tuple[SICDType]
        """

        if self._sicd_meta is None:
            return None
        elif isinstance(self._sicd_meta, tuple):
            return self._sicd_meta
        else:
            return (self._sicd_meta, )

    def get_data_size_as_tuple(self):
        """
        Get the data size wrapped in a tuple - for simplicity and ease of use.

        Returns
        -------
        Tuple[Tuple[int, int]]
        """

        if isinstance(self._chipper, tuple):
            return self._data_size
        else:
            return (self._data_size, )

    def _validate_index(self, index):
        if isinstance(self._chipper, BaseChipper) or index is None:
            return 0

        if not isinstance(index, integer_types):
            raise ValueError('Cannot slice in multiple indices on the third dimension.')
        index = int(index)
        siz = len(self._chipper)
        if not (-siz < index < siz):
            raise ValueError('index must be in the range ({}, {})'.format(-siz, siz))
        return index

    def _validate_slice(self, item):
        if isinstance(item, tuple):
            if len(item) > 3:
                raise ValueError(
                    'Reader received slice argument {}. We cannot slice on more than '
                    'three dimensions.'.format(item))
            if len(item) == 3:
                index = self._validate_index(item[2])
                return item[:2], index
        return item, 0

    def __call__(self, range1, range2, index=0):
        """
        Reads and fetches data. Note that :code:`reader(range1, range2, index)` is an alias
        for :code:`reader.read_chip(range1, range2, index)`.

        Parameters
        ----------
        range1 : None|int|tuple
        range2 : None|int|tuple
        index : None|int

        Returns
        -------
        numpy.ndarray
        """

        if isinstance(self._chipper, tuple):
            index = self._validate_index(index)
            return self._chipper[index](range1, range2)
        else:
            return self._chipper(range1, range2)

    def __getitem__(self, item):
        """
        Reads and returns data using more traditional to python slice functionality.
        After slice interpretation, this is analogous to :func:`__call__` or :func:`read_chip`.

        Parameters
        ----------
        item : None|int|slice|tuple

        Returns
        -------
        numpy.ndarray
        """

        item, index = self._validate_slice(item)
        if isinstance(self._chipper, tuple):
            return self._chipper[index].__getitem__(item)
        else:
            return self._chipper.__getitem__(item)

    def read_chip(self, dim1range, dim2range, index=None):
        """
        Read the given section of data as an array.

        Parameters
        ----------
        dim1range : None|int|Tuple[int, int]|Tuple[int, int, int]
            The row data selection of the form `[start, [stop, [stride]]]`, and
            `None` defaults to all rows (i.e. `(0, NumRows, 1)`)
        dim2range : None|int|Tuple[int, int]|Tuple[int, int, int]
            The column data selection of the form `[start, [stop, [stride]]]`, and
            `None` defaults to all rows (i.e. `(0, NumCols, 1)`)
        index : int|None
            Relative to which sicd/chipper, and only used in the event of multiple
            sicd/chippers. Defaults to `0`, if not provided.

        Returns
        -------
        numpy.ndarray
            The complex data, explicitly of dtype=complex.64. Be sure to upcast to
            complex128 if so desired.

        Examples
        ------------
        :code:`data = reader.read_chip((start1, stop1, stride1), (start2, stop2, stride2))`

        Also available is basic call syntax

        .. code-block::

            data = reader(dim1range, dim2range, index).

        Another alternative is slice syntax

        .. code-block:: python

            data = reader[start1:stop1:stride1, start:stop:stride]  # or
            data = reader[start:stop:stride, start:stop:stride, index]

        Here the slice on index (dimension 3) is limited to a single integer, and
        no slice on index :code:`reader[:, :]` will default to `index=0`,
        :code:`reader[:, :, 0]` (where appropriate).
        """

        if isinstance(self._chipper, tuple):
            index = self._validate_index(index)
            return self._chipper[index](dim1range, dim2range)
        else:
            return self._chipper(dim1range, dim2range)


class SubsetReader(BaseReader):
    """Permits extraction from a particular subset of the possible data range"""
    __slots__ = ('_parent_reader', )

    def __init__(self, parent_reader, sicd_meta, dim1bounds, dim2bounds):
        """

        Parameters
        ----------
        parent_reader : BaseReader
        sicd_meta : SICDType
        dim1bounds : tuple
        dim2bounds : tuple
        """

        self._parent_reader = parent_reader
        # noinspection PyProtectedMember
        chipper = SubsetChipper(parent_reader._chipper, dim1bounds, dim2bounds)
        super(SubsetReader, self).__init__(sicd_meta, chipper)


#################
# Base Writer definition

class AbstractWriter(object):
    """Abstract file writer class for SICD data"""
    __slots__ = ('_file_name', )

    def __init__(self, file_name):
        """

        Parameters
        ----------
        file_name : str
        """

        self._file_name = file_name
        if not os.path.exists(self._file_name):
            with open(self._file_name, 'wb') as fi:
                fi.write(b'')

    def close(self):
        """
        Completes any necessary final steps.

        Returns
        -------
        None
        """

        pass

    def write_chip(self, data, start_indices=(0, 0)):
        """
        Write the data to the file(s). This is an alias to :code:`writer(data, start_indices)`.

        Parameters
        ----------
        data : numpy.ndarray
            the complex data
        start_indices : tuple[int, int]
            the starting index for the data.

        Returns
        -------
        None
        """

        self.__call__(data, start_indices=start_indices)

    def __call__(self, data, start_indices=(0, 0)):
        """
        Write the data to the file(s).

        Parameters
        ----------
        data : numpy.ndarray
            the complex data
        start_indices : Tuple[int, int]
            the starting index for the data.

        Returns
        -------
        None
        """

        raise NotImplementedError

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if exception_type is None:
            self.close()
        else:
            logging.error(
                'The {} file writer generated an exception during processing. The file {} may be '
                'only partially generated and corrupt.'.format(self.__class__.__name__, self._file_name))
            # The exception will be reraised.
            # It's unclear how any exception could be caught.


def validate_sicd_for_writing(sicd_meta):
    """
    Helper method which ensures the provided SICD structure provides enough
    information to support file writing, as well as ensures a few basic items
    are populated as appropriate.

    Parameters
    ----------
    sicd_meta : SICDType

    Returns
    -------
    SICDType
        This returns a deep copy of the provided SICD structure, with any
        necessary modifications.
    """

    if not isinstance(sicd_meta, SICDType):
        raise ValueError('sicd_meta is required to be an instance of SICDType, got {}'.format(type(sicd_meta)))
    if sicd_meta.ImageData is None:
        raise ValueError('The sicd_meta has un-populated ImageData, and nothing useful can be inferred.')
    if sicd_meta.ImageData.NumCols is None or sicd_meta.ImageData.NumRows is None:
        raise ValueError('The sicd_meta has ImageData with unpopulated NumRows or NumCols, '
                         'and nothing useful can be inferred.')
    if sicd_meta.ImageData.PixelType is None:
        logging.warning('The PixelType for sicd_meta is unset, so defaulting to RE32F_IM32F.')
        sicd_meta.ImageData.PixelType = 'RE32F_IM32F'

    sicd_meta = sicd_meta.copy()

    profile = '{} {}'.format(__title__, __version__)
    if sicd_meta.ImageCreation is None:
        sicd_meta.ImageCreation = ImageCreationType(
            Application=profile,
            DateTime=numpy.datetime64(datetime.now()),
            Profile=profile)
    else:
        sicd_meta.ImageCreation.Profile = profile
        if sicd_meta.ImageCreation.DateTime is None:
            sicd_meta.ImageCreation.DateTime = numpy.datetime64(datetime.now())
    return sicd_meta


class BaseWriter(AbstractWriter):
    """
    Abstract file writer class for SICD data
    """

    __slots__ = ('_file_name', '_sicd_meta', )

    def __init__(self, file_name, sicd_meta):
        """

        Parameters
        ----------
        file_name : str
        sicd_meta : SICDType
        """

        super(BaseWriter, self).__init__(file_name)
        self._sicd_meta = validate_sicd_for_writing(sicd_meta)

    @property
    def sicd_meta(self):
        """
        SICDType: the sicd metadata
        """

        return self._sicd_meta

    def __call__(self, data, start_indices=(0, 0)):
        raise NotImplementedError
